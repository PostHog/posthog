use std::{io::Stdout, thread::JoinHandle, time::Duration};

use anyhow::Error;
use crossterm::event::{self, Event, KeyCode, KeyEvent, KeyModifiers};
use ratatui::{
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    prelude::CrosstermBackend,
    style::{Color, Style, Stylize},
    widgets::{Block, BorderType, Paragraph, Row, Table, TableState},
    Frame, Terminal,
};

use serde::{Deserialize, Serialize};
use tui_textarea::TextArea;

use crate::utils::{
    auth::Token,
    homedir::posthog_home_dir,
    query::{self, HogQLQueryErrorResponse, HogQLQueryResponse, HogQLQueryResult},
};

pub struct QueryTui {
    host: String,
    creds: Token,
    current_result: Option<HogQLQueryResult>,
    lower_panel_state: Option<LowerPanelState>,
    bg_query_handle: Option<JoinHandle<Result<HogQLQueryResult, Error>>>,
    focus: Focus,
    debug: bool,
    state_dirty: bool,
}

#[allow(clippy::large_enum_variant)]
enum LowerPanelState {
    TableState(TableState),
    DebugState(TextArea<'static>),
}

#[derive(Clone, Copy)]
enum Focus {
    Editor,
    Output,
}

#[derive(Serialize, Deserialize)]
struct PersistedEditorState {
    lines: Vec<String>,
    current_result: Option<HogQLQueryResult>,
}

impl QueryTui {
    pub fn new(creds: Token, host: String, debug: bool) -> Self {
        Self {
            current_result: None,
            lower_panel_state: None,
            creds,
            host,
            focus: Focus::Editor,
            debug,
            bg_query_handle: None,
            state_dirty: false,
        }
    }

    fn draw_outer(&mut self, frame: &mut Frame) -> Rect {
        let area = frame.area();

        let outer = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Fill(1)].as_ref())
            .split(area);

        let mut top_title =
            "Posthog Query Editor - Ctrl+R to run query, ESC to quit, Ctrl+F to switch focus"
                .to_string();
        if self.bg_query_handle.is_some() {
            top_title.push_str(" (Running query, Ctrl+C to cancel)");
        }

        let border_color = if self.bg_query_handle.is_some() {
            Color::LightBlue
        } else {
            Color::Black
        };

        let outer_block = Block::bordered()
            .title_top(top_title)
            .border_type(BorderType::Rounded)
            .border_style(Style::new().bg(border_color))
            .title_alignment(Alignment::Center);

        let inner_area = outer_block.inner(outer[0]);

        frame.render_widget(outer_block, outer[0]);

        inner_area
    }

    fn save_editor_state(&self, lines: Vec<String>) -> Result<(), Error> {
        if !self.state_dirty {
            return Ok(());
        }
        let home_dir = posthog_home_dir();
        let editor_state_path = home_dir.join("editor_state.json");
        let state = PersistedEditorState {
            lines,
            current_result: self.current_result.clone(),
        };

        let state_str = serde_json::to_string(&state)?;
        std::fs::write(editor_state_path, state_str)?;
        Ok(())
    }

    fn load_editor_state(&mut self) -> Result<Vec<String>, Error> {
        let home_dir = posthog_home_dir();
        let editor_state_path = home_dir.join("editor_state.json");
        if !editor_state_path.exists() {
            return Ok(vec![]);
        }

        let state_str = std::fs::read_to_string(editor_state_path)?;
        let Ok(state): Result<PersistedEditorState, _> = serde_json::from_str(&state_str) else {
            return Ok(vec![]);
        };
        self.current_result = state.current_result;
        Ok(state.lines)
    }

    fn draw_lower_panel(&mut self, frame: &mut Frame, area: Rect) {
        let is_focus = matches!(self.focus, Focus::Output);
        match (&self.current_result, self.debug) {
            (Some(Ok(res)), false) => {
                let table = get_response_table(res, is_focus);
                let mut ts =
                    if let Some(LowerPanelState::TableState(ts)) = self.lower_panel_state.take() {
                        ts
                    } else {
                        TableState::default()
                    };

                frame.render_stateful_widget(table, area, &mut ts);
                self.lower_panel_state = Some(LowerPanelState::TableState(ts));
            }
            (Some(Ok(res)), true) => {
                let debug_display =
                    if let Some(LowerPanelState::DebugState(ta)) = self.lower_panel_state.take() {
                        ta
                    } else {
                        get_debug_display(res)
                    };

                let debug_display = style_debug_display(debug_display, is_focus);
                frame.render_widget(&debug_display, area);
                self.lower_panel_state = Some(LowerPanelState::DebugState(debug_display));
            }
            (Some(Err(err)), _) => {
                let paragraph = get_error_display(err, is_focus);
                frame.render_widget(paragraph, area);
            }
            (None, _) => {}
        }
    }

    fn draw(&mut self, frame: &mut Frame, text_area: &TextArea) {
        let inner_area = self.draw_outer(frame);

        let mut panel_count: usize = 1;
        if self.current_result.is_some() {
            panel_count += 1;
        }

        // TODO - figure out nicer dynamic constraints?
        let mut constraints = vec![];
        constraints.extend(vec![Constraint::Fill(1); panel_count]);

        let inner_panels = Layout::default()
            .direction(Direction::Vertical)
            .constraints(constraints)
            .split(inner_area);

        frame.render_widget(text_area, inner_panels[0]);
        if inner_panels.len() > 1 {
            self.draw_lower_panel(frame, inner_panels[1]);
        }
    }

    fn handle_bg_query(&mut self) -> Result<(), Error> {
        let Some(handle) = self.bg_query_handle.take() else {
            return Ok(());
        };

        if !handle.is_finished() {
            self.bg_query_handle = Some(handle);
            return Ok(());
        }

        let res = handle.join().expect("Task did not panic")?;

        self.current_result = Some(res);
        self.state_dirty = true;
        Ok(())
    }

    fn handle_keypress(&mut self, text_area: &mut TextArea, key: KeyEvent) -> Result<(), Error> {
        if key.code == KeyCode::Char('r') && key.modifiers == KeyModifiers::CONTROL {
            let lines = text_area.lines().to_vec();
            self.spawn_bg_query(lines);
            return Ok(()); // Simply starting the query doesn't modify the state
        }

        if key.code == KeyCode::Char('c') && key.modifiers == KeyModifiers::CONTROL {
            // TODO - we don't have proper task cancellation here, but this "cancels" the query from the
            // user's perspective - they will never see the results
            self.bg_query_handle = None;
            return Ok(()); // As above, this doesn't modify the state
        }

        if key.code == KeyCode::Char('f') && key.modifiers == KeyModifiers::CONTROL {
            self.focus = match self.focus {
                Focus::Editor => Focus::Output,
                Focus::Output => Focus::Editor,
            };
            return Ok(()); // As above, this doesn't modify the state
        }

        if key.code == KeyCode::Char('q') && key.modifiers == KeyModifiers::CONTROL {
            self.current_result = None;
            self.lower_panel_state = None;
            self.state_dirty = true; // We've discarded the current result
            return Ok(());
        }

        match self.focus {
            Focus::Editor => {
                text_area.input(key);
                self.state_dirty = true; // Keys into the editor modify the state
            }
            Focus::Output => {
                self.handle_output_event(key);
            }
        }

        Ok(())
    }

    fn handle_events(&mut self, text_area: &mut TextArea) -> Result<Option<String>, Error> {
        self.handle_bg_query()?;
        self.save_editor_state(text_area.lines().to_vec())?;
        if !event::poll(Duration::from_millis(17))? {
            return Ok(None);
        }

        if let Event::Key(key) = event::read()? {
            if key.code == KeyCode::Esc {
                let last_query = text_area.lines().join("\n");
                return Ok(Some(last_query));
            }

            self.handle_keypress(text_area, key)?;
        }

        Ok(None)
    }

    fn handle_output_event(&mut self, key: KeyEvent) {
        match &mut self.lower_panel_state {
            Some(LowerPanelState::TableState(ref mut ts)) => {
                if key.code == KeyCode::Down {
                    ts.select_next();
                } else if key.code == KeyCode::Up {
                    ts.select_previous();
                }
            }
            Some(LowerPanelState::DebugState(ta)) => {
                ta.input(key);
            }
            _ => {}
        }
    }

    fn enter_draw_loop(
        &mut self,
        mut terminal: Terminal<CrosstermBackend<Stdout>>,
    ) -> Result<String, Error> {
        let lines = self.load_editor_state()?;
        let mut text_area = TextArea::new(lines);
        loop {
            terminal.draw(|frame| self.draw(frame, &text_area))?;
            if let Some(query) = self.handle_events(&mut text_area)? {
                return Ok(query);
            }
        }
    }

    fn spawn_bg_query(&mut self, lines: Vec<String>) {
        let query = lines.join("\n");
        let query_endpoint = format!("{}/api/environments/{}/query", self.host, self.creds.env_id);
        let m_token = self.creds.token.clone();
        let handle =
            std::thread::spawn(move || query::run_query(&query_endpoint, &m_token, &query));

        // We drop any previously running thread handle here, but don't kill the thread... this is fine,
        // I think. The alternative is to switch to tokio and get true task cancellation, but :shrug:,
        // TODO later I guess
        self.bg_query_handle = Some(handle);
    }
}

pub fn start_query_editor(host: &str, token: Token, debug: bool) -> Result<String, Error> {
    let terminal = ratatui::init();

    let mut app = QueryTui::new(token, host.to_string(), debug);
    let res = app.enter_draw_loop(terminal);
    ratatui::restore();
    res
}

fn get_response_table<'a>(response: &HogQLQueryResponse, is_focus: bool) -> Table<'a> {
    let cols = &response.columns;
    let widths = cols.iter().map(|_| Constraint::Fill(1)).collect::<Vec<_>>();
    let mut rows: Vec<Row> = Vec::with_capacity(response.results.len());
    for row in &response.results {
        let mut row_data = Vec::with_capacity(cols.len());
        for _ in cols {
            let value = row[row_data.len()].to_string();
            row_data.push(value.to_string());
        }
        rows.push(Row::new(row_data));
    }

    let border_color = if is_focus {
        Color::Cyan
    } else {
        Color::DarkGray
    };

    let table = Table::new(rows, widths)
        .column_spacing(1)
        .header(Row::new(cols.clone()).style(Style::new().bold().bg(Color::LightBlue)))
        .block(
            ratatui::widgets::Block::default()
                .title("Query Results (Ctrl+Q to clear)")
                .title_style(Style::new().bold().fg(Color::White).bg(Color::DarkGray))
                .borders(ratatui::widgets::Borders::ALL)
                .border_style(Style::new().fg(Color::White).bg(border_color)),
        )
        .row_highlight_style(Style::new().bold().bg(Color::DarkGray))
        .highlight_symbol(">");

    table
}

fn get_error_display<'c>(err: &HogQLQueryErrorResponse, is_focus: bool) -> Paragraph<'c> {
    let mut lines = vec![format!("Error: {}", err.error_type)];
    lines.push(format!("Code: {}", err.code));
    lines.push(format!("Detail: {}", err.detail));

    let border_color = if is_focus {
        Color::Cyan
    } else {
        Color::LightRed
    };

    Paragraph::new(lines.join("\n"))
        .style(Style::new().fg(Color::Red))
        .block(
            Block::default()
                .title("Error (Ctrl+Q to clear)")
                .title_style(Style::new().bold().fg(Color::White).bg(Color::Red))
                .borders(ratatui::widgets::Borders::ALL)
                .border_style(Style::new().fg(Color::White).bg(border_color)),
        )
}

// A function that returns a text area with the json
fn get_debug_display(response: &HogQLQueryResponse) -> TextArea<'static> {
    let json = serde_json::to_string_pretty(&response)
        .expect("Can serialize response to json")
        .lines()
        .map(|s| s.to_string())
        .collect();
    let mut ta = TextArea::new(json);
    ta.set_line_number_style(Style::new().bg(Color::DarkGray));
    ta
}

fn style_debug_display(mut ta: TextArea, is_focus: bool) -> TextArea {
    let border_color = if is_focus {
        Color::Cyan
    } else {
        Color::DarkGray
    };

    ta.set_block(
        Block::default()
            .title("Debug (Ctrl+Q to clear)")
            .title_style(Style::new().bold().fg(Color::White).bg(Color::Red))
            .borders(ratatui::widgets::Borders::ALL)
            .border_style(Style::new().fg(Color::White).bg(border_color)),
    );

    ta
}
