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
    steps: Vec<i32>,
}

#[derive(Deserialize)]
struct Args {
    num_steps: i32,
    conversion_window_limit: u64,
    breakdown_attribution_type: String,
    funnel_order_type: String,
    prop_vals: Vec<PropVal>,
    value: Vec<Event>,
}

#[derive(Serialize)]
struct Result(i32, PropVal, Vec<f64>, Vec<Vec<Uuid>>);

const MAX_REPLAY_EVENTS: usize = 10;

#[inline(always)]
fn parse_args(line: &str) -> Args {
    serde_json::from_str(line).expect("Invalid JSON input")
}

#[inline(always)]
fn calculate_funnel_from_user_events(
    num_steps: i32,
    conversion_window_limit_seconds: u64,
    breakdown_attribution_type: &str,
    funnel_order_type: &str,
    prop_vals: Vec<PropVal>,
    events: Vec<Event>,
) -> Vec<Result> {
    let default_entered_timestamp = EnteredTimestamp {
        timestamp: 0.0,
        timings: vec![],
        uuids: vec![],
    };
    let breakdown_step = if breakdown_attribution_type.starts_with("step_") {
        breakdown_attribution_type[5..].parse::<usize>().ok()
    } else {
        None
    };

    let mut results: Vec<Result> = Vec::with_capacity(prop_vals.len());

    for prop_val in prop_vals {
        let mut max_step = (0, default_entered_timestamp.clone());
        let mut entered_timestamp = vec![default_entered_timestamp.clone(); (num_steps + 1) as usize];
        let mut event_uuids: Vec<Vec<Uuid>> = repeat(Vec::new()).take(num_steps as usize).collect();
        let mut add_max_step = true;

        let filtered_events  = events.iter()
            .filter(|e| {
                if breakdown_attribution_type == "all_events" {
                    e.breakdown == prop_val
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
                if !process_event(
                    &events_with_same_timestamp[0],
                    &mut entered_timestamp,
                    &prop_val,
                    &mut event_uuids,
                    conversion_window_limit_seconds,
                    funnel_order_type,
                    &mut max_step,
                    breakdown_step,
                    &mut results,
                ) {
                    add_max_step = false;
                    break;
                }
            } else {
                // Handle permutations for events with the same timestamp
                let mut entered_timestamps: Vec<_> = vec![];
                for perm in events_with_same_timestamp.iter().permutations(events_with_same_timestamp.len()) {
                    entered_timestamps.push(entered_timestamp.clone());
                    for event in perm {
                        if !process_event(
                            &event,
                            &mut entered_timestamps.last_mut().unwrap(),
                            &prop_val,
                            &mut event_uuids,
                            conversion_window_limit_seconds,
                            funnel_order_type,
                            &mut max_step,
                            breakdown_step,
                            &mut results,
                        ) {
                            add_max_step = false;
                            break;
                        }
                    }
                }
                for i in 0..entered_timestamp.len() {
                    entered_timestamp[i] = entered_timestamps.iter().max_by_key(|x| x[i].timestamp as i32).unwrap()[i].clone();
                }
            }

            if entered_timestamp[num_steps as usize].timestamp > 0.0 {
                break;
            }
        }

        if add_max_step {
            let final_index = max_step.0;
            let final_value = &max_step.1;

            for i in 0..final_index {
                //if event_uuids[i].len() >= MAX_REPLAY_EVENTS && !event_uuids[i].contains(&final_value.uuids[i]) {
                // Always put the actual event uuids first, we use it to extract timestamps
                // This might create duplicates, but that's fine (we can remove it in clickhouse)
                event_uuids[i].insert(0, final_value.uuids[i].clone());
            }
            results.push(Result(
                final_index as i32 - 1,
                prop_val,
                final_value.timings.windows(2).map(|w| w[1] - w[0]).collect(),
                event_uuids
            ))
        }
    }
    results
}

#[inline(always)]
fn process_event(
    event: &Event,
    entered_timestamp: &mut Vec<EnteredTimestamp>,
    prop_val: &PropVal,
    event_uuids: &mut Vec<Vec<Uuid>>,
    conversion_window_limit_seconds: u64,
    funnel_order_type: &str,
    max_step: &mut (usize, EnteredTimestamp),
    breakdown_step: Option<usize>,
    results: &mut Vec<Result>
) -> bool {

    for step in event.steps.iter().rev() {
        let mut exclusion = false;
        let step = (if *step < 0 {
            exclusion = true;
            -*step
        } else {
            *step
        }) as usize;

        let in_match_window = (event.timestamp - entered_timestamp[step - 1].timestamp) <= conversion_window_limit_seconds as f64;
        let already_reached_this_step = entered_timestamp[step].timestamp == entered_timestamp[step - 1].timestamp
            && entered_timestamp[step].timestamp != 0.0;

        if in_match_window && !already_reached_this_step {
            if exclusion {
                results.push(Result ( -1, prop_val.clone(), vec![], vec![] ));
                return false;
            }
            let is_unmatched_step_attribution = breakdown_step.map( |breakdown_step| step == breakdown_step - 1 ).unwrap_or(false) && *prop_val != event.breakdown;
            if !is_unmatched_step_attribution {
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
                if event_uuids[step - 1].len() < MAX_REPLAY_EVENTS - 1 {
                    event_uuids[step - 1].push(event.uuid);
                }
            }
            if step > max_step.0 {
                *max_step = (step, entered_timestamp[step].clone());
            }
        }
    }

    if funnel_order_type == "strict" {
        for i in 1..entered_timestamp.len() {
            if !event.steps.contains(&(i as i32)) {
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

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        if let Ok(line) = line {
            let args = parse_args(&line);
            let result = calculate_funnel_from_user_events(
                args.num_steps,
                args.conversion_window_limit,
                &args.breakdown_attribution_type,
                &args.funnel_order_type,
                args.prop_vals,
                args.value
            );
            let output = json!({ "result": result });
            writeln!(stdout, "{}", output).unwrap();
            stdout.flush().unwrap();
        }
    }
}