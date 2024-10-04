use serde::{Deserialize, Serialize};
use serde_json::json;
use std::io::{self, BufRead, Write};
use std::iter::repeat;
use itertools::Itertools;
use uuid::Uuid;

#[derive(Clone, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
enum PropVal {
    String(String),
    Vec(Vec<String>),
    Int(u32),
}

#[derive(Clone, Deserialize)]
struct EnteredTimestamp {
    timestamp: f64,
    timings: Vec<f64>,
    uuids: Vec<Uuid>,
}

#[derive(Clone, Deserialize)]
struct Event {
    timestamp: f64,
    uuid: Uuid,
    breakdown: PropVal,
    steps: Vec<i8>,
}

#[derive(Deserialize)]
struct Args {
    num_steps: usize,
    // Converstion Window Limit in Seconds
    conversion_window_limit: u64,
    breakdown_attribution_type: String,
    funnel_order_type: String,
    prop_vals: Vec<PropVal>,
    value: Vec<Event>,
}

#[derive(Serialize)]
struct Result(i8, PropVal, Vec<f64>, Vec<Vec<Uuid>>);

struct Vars {
    max_step: (usize, EnteredTimestamp),
    event_uuids: Vec<Vec<Uuid>>,
}

struct AggregateFunnelRow {
    // vars: Vars,
    // event_uuids: Vec<Vec<Uuid>>,
    breakdown_step: Option<usize>,
    results: Vec<Result>,
}

const MAX_REPLAY_EVENTS: usize = 10;

const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    timings: vec![],
    uuids: vec![],
};

#[inline(always)]
fn parse_args(line: &str) -> Args {
    serde_json::from_str(line).expect("Invalid JSON input")
}

impl AggregateFunnelRow {
    #[inline(always)]
    fn calculate_funnel_from_user_events(&mut self, args: &Args) -> &Vec<Result> {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        args.prop_vals.iter().for_each(|prop_val| self.loop_prop_val(args, prop_val));

        &self.results
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) {
        let mut vars = Vars {
            max_step: (0, DEFAULT_ENTERED_TIMESTAMP.clone()),
            event_uuids: repeat(Vec::new()).take(args.num_steps).collect(),
        };
        let mut entered_timestamp = vec![DEFAULT_ENTERED_TIMESTAMP.clone(); args.num_steps + 1];

        let filtered_events = args.value.iter()
            .filter(|e| {
                if args.breakdown_attribution_type == "all_events" {
                    e.breakdown == *prop_val
                } else {
                    true
                }
            })
            .group_by(|e| e.timestamp);

        for (timestamp, events_with_same_timestamp) in &filtered_events {
            let events_with_same_timestamp: Vec<_> = events_with_same_timestamp.collect();
            entered_timestamp[0] = EnteredTimestamp {
                timestamp,
                timings: vec![],
                uuids: vec![],
            };

            if events_with_same_timestamp.len() == 1 {
                if !self.process_event(
                    args,
                    &mut vars,
                    &events_with_same_timestamp[0],
                    &mut entered_timestamp,
                    prop_val,
                    false
                ) {
                    return;
                }
            } else if events_with_same_timestamp.iter().map(|x| &x.steps).all_equal() {
                // Deal with the case where they are all the same event
                for event in events_with_same_timestamp {
                    if !self.process_event(
                        args,
                        &mut vars,
                        event,
                        &mut entered_timestamp,
                        prop_val,
                        false
                    ) {
                        return;
                    }
                }
            } else {
                // Handle permutations for different events with the same timestamp
                // The behavior here is a little undefined, we don't handle it for strict funnels or exclusions
                // Could add more optimizations here but shouldn't be very common
                let sorted_events = events_with_same_timestamp
                    .iter()
                    .flat_map(|&event| {
                        event.steps
                            .iter()
                            .filter(|&&step| step > 0)
                            .map(move |&step| Event { steps: vec![step], ..event.clone() })
                    }).sorted_by_key(|event| event.steps[0]);

                for event in sorted_events {
                    if !self.process_event(
                        args,
                        &mut vars,
                        &event,
                        &mut entered_timestamp,
                        &prop_val,
                        true
                    ) {
                        return;
                    }
                }
            }

            // If we hit the goal, we can terminate early
            if entered_timestamp[args.num_steps].timestamp > 0.0 {
                break;
            }
        }

        // Find the furthest step we have made it to and print it
        let final_index = vars.max_step.0;
        let final_value = &vars.max_step.1;

        for i in 0..final_index {
            //if event_uuids[i].len() >= MAX_REPLAY_EVENTS && !event_uuids[i].contains(&final_value.uuids[i]) {
            // Always put the actual event uuids first, we use it to extract timestamps
            // This might create duplicates, but that's fine (we can remove it in clickhouse)
            vars.event_uuids[i].insert(0, final_value.uuids[i].clone());
        }
        self.results.push(Result(
            final_index as i8 - 1,
            prop_val.clone(),
            final_value.timings.windows(2).map(|w| w[1] - w[0]).collect(),
            vars.event_uuids,
        ))
    }

    #[inline(always)]
    fn process_event(
        &mut self,
        args: &Args,
        vars: &mut Vars,
        event: &Event,
        entered_timestamp: &mut Vec<EnteredTimestamp>,
        prop_val: &PropVal,
        validate_event_reuse: bool
    ) -> bool {
        for step in event.steps.iter().rev() {
            let mut exclusion = false;
            let step = (if *step < 0 {
                exclusion = true;
                -*step
            } else {
                *step
            }) as usize;

            let in_match_window = (event.timestamp - entered_timestamp[step - 1].timestamp) <= args.conversion_window_limit as f64;
            let already_reached_this_step = entered_timestamp[step].timestamp == entered_timestamp[step - 1].timestamp
                && entered_timestamp[step].timestamp != 0.0;

            if in_match_window && !already_reached_this_step {
                if exclusion {
                    self.results.push(Result(-1, prop_val.clone(), vec![], vec![]));
                    return false;
                }
                let is_unmatched_step_attribution = self.breakdown_step.map(|breakdown_step| step == breakdown_step - 1).unwrap_or(false) && *prop_val != event.breakdown;
                let already_used_event = validate_event_reuse && entered_timestamp[step-1].uuids.contains(&event.uuid);
                if !is_unmatched_step_attribution && !already_used_event {
                    entered_timestamp[step] = EnteredTimestamp {
                        timestamp: entered_timestamp[step - 1].timestamp,
                        timings: {
                            let mut timings = entered_timestamp[step - 1].timings.clone();
                            timings.push(event.timestamp);
                            timings
                        },
                        uuids: {
                            let mut uuids = entered_timestamp[step - 1].uuids.clone();
                            uuids.push(event.uuid);
                            uuids
                        },
                    };
                    if vars.event_uuids[step - 1].len() < MAX_REPLAY_EVENTS - 1 {
                        vars.event_uuids[step - 1].push(event.uuid);
                    }
                    if step > vars.max_step.0 {
                        vars.max_step = (step, entered_timestamp[step].clone());
                    }
                }
            }
        }

        if args.funnel_order_type == "strict" {
            for i in 1..entered_timestamp.len() {
                if !event.steps.contains(&(i as i8)) {
                    entered_timestamp[i] = EnteredTimestamp {
                        timestamp: 0.0,
                        timings: vec![],
                        uuids: vec![],
                    };
                }
            }
        }

        true
    }
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        if let Ok(line) = line {
            let args = parse_args(&line);
            let mut aggregate_funnel_row = AggregateFunnelRow {
                results: Vec::with_capacity(args.prop_vals.len()),
                breakdown_step: Option::None,
            };
            let result = aggregate_funnel_row.calculate_funnel_from_user_events(&args);
            let output = json!({ "result": result });
            writeln!(stdout, "{}", output).unwrap();
            stdout.flush().unwrap();
        }
    }
}