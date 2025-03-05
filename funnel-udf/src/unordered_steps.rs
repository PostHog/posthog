use crate::steps::{Args, EnteredTimestamp, Event, Result};
use crate::PropVal;
use std::collections::VecDeque;
use std::iter::repeat;
use uuid::Uuid;

struct Vars {
    max_step: (usize, EnteredTimestamp),
    events_by_step: Vec<VecDeque<Event>>,
    num_steps_completed: usize,
}

pub struct AggregateFunnelRowUnordered {
    pub breakdown_step: Option<usize>,
    pub results: Vec<Result>,
}

const DEFAULT_ENTERED_TIMESTAMP: EnteredTimestamp = EnteredTimestamp {
    timestamp: 0.0,
    excluded: false,
    timings: vec![],
    uuids: vec![],
};

impl AggregateFunnelRowUnordered {
    #[inline(always)]
    pub fn calculate_funnel_from_user_events(&mut self, args: &Args) -> &Vec<Result> {
        if args.breakdown_attribution_type.starts_with("step_") {
            self.breakdown_step = args.breakdown_attribution_type[5..].parse::<usize>().ok()
        }

        args.prop_vals
            .iter()
            .for_each(|prop_val| self.loop_prop_val(args, prop_val));

        &self.results
    }

    #[inline(always)]
    fn loop_prop_val(&mut self, args: &Args, prop_val: &PropVal) {
        let mut vars = Vars {
            // For each step, we store a deque of events (in chronological order) that have reached that step
            events_by_step: repeat(VecDeque::new()).take(args.num_steps).collect(),
            // Max step keeps track of the place where we have matched the most events
            max_step: (0, DEFAULT_ENTERED_TIMESTAMP.clone()),
            num_steps_completed: 0,
        };

        let (exclusions, non_exclusions): (Vec<&Event>, Vec<&Event>) = args
            .value
            .iter()
            .filter(|e| {
                if args.breakdown_attribution_type == "all_events" {
                    e.breakdown == *prop_val
                } else {
                    true
                }
            })
            .partition(|&event| event.steps.iter().all(|&step| step < 0));

        for event in non_exclusions {
            self.process_event(args, &mut vars, event, prop_val);
        }

        // Find the furthest step we have made it to and print it
        let final_index = vars.max_step.0;
        let final_value = &vars.max_step.1;

        // Check for exclusions
        for exclusion in exclusions {
            // Check if the exclusion timestamp falls within the range of our max step
            if !vars.max_step.1.timings.is_empty() {
                let start_timestamp = vars.max_step.1.timings.first().unwrap();
                let end_timestamp = vars.max_step.1.timings.last().unwrap();

                if exclusion.timestamp > *start_timestamp && exclusion.timestamp < *end_timestamp {
                    // Exclusion falls within our funnel path, mark as excluded
                    self.results
                        .push(Result(-1, prop_val.clone(), vec![], vec![]));
                    return;
                }
            }
        }

        self.results.push(Result(
            final_index as i8 - 1,
            prop_val.clone(),
            final_value
                .timings
                .windows(2)
                .map(|w| w[1] - w[0])
                .collect(),
            vars.max_step
                .1
                .uuids
                .iter()
                .map(|uuid| vec![*uuid])
                .collect(),
        ))
    }

    #[inline(always)]
    fn process_event(&mut self, args: &Args, vars: &mut Vars, event: &Event, prop_val: &PropVal) {
        // 1. Push the event to the back of the deque. If it matches multiple steps, push it to the one whose last element is the further from now
        // 2. Delete all events that are out of the match window
        // 3. Update some value to store the size of the match now (so we know if we can update max without iterating through them all again)

        // If it matches one step, update that step
        // The assumption here is that there is only one way to fulfill each step. For example, if the same event fulfills steps 2 and 7, there is no other event
        // that fulfills just step 2. If we add that functionality, this gets more complicated.

        // Find the step with the minimum timestamp.
        let min_timestamp_step = *event
            .steps
            .iter()
            .min_by_key(|&&step| {
                let step = step as usize;
                ordered_float::OrderedFloat(
                    vars.events_by_step[step - 1]
                        .back()
                        .map(|e| e.timestamp)
                        .unwrap_or(0.0),
                )
            })
            .unwrap() as usize;

        if self.breakdown_step.is_some()
            && vars.num_steps_completed == self.breakdown_step.unwrap()
            && *prop_val != event.breakdown
        {
            // If this step doesn't match the requested attribution, it's not valid
            return;
        }

        if vars.events_by_step[min_timestamp_step - 1].is_empty() {
            vars.num_steps_completed += 1;
        }
        vars.events_by_step[min_timestamp_step - 1].push_back(event.clone());

        // 2. Delete all events that are out of the match window
        for index in 0..vars.events_by_step.len() {
            if !vars.events_by_step[index].is_empty() {
                loop {
                    let front_event = vars.events_by_step[index].front();
                    if front_event.is_none() {
                        vars.num_steps_completed -= 1;
                        break;
                    }

                    let front_event = front_event.unwrap();
                    if event.timestamp - front_event.timestamp > args.conversion_window_limit as f64
                    {
                        vars.events_by_step[index].pop_front();
                    } else {
                        break;
                    }
                }
            }
        }

        // 3. Update max_step if we've completed more steps than before
        if vars.num_steps_completed > vars.max_step.0 {
            let mut timestamps_with_uuids: Vec<(f64, Uuid)> = vars
                .events_by_step
                .iter()
                .filter_map(|deque| deque.front().map(|e| (e.timestamp, e.uuid)))
                .collect();

            timestamps_with_uuids.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

            let timings = timestamps_with_uuids
                .iter()
                .map(|(t, _)| *t)
                .collect::<Vec<f64>>();
            let uuids = timestamps_with_uuids
                .iter()
                .map(|(_, u)| *u)
                .collect::<Vec<Uuid>>();

            vars.max_step = (
                vars.num_steps_completed,
                EnteredTimestamp {
                    timestamp: event.timestamp,
                    excluded: false,
                    timings: timings,
                    uuids: uuids,
                },
            );
        }
    }
}
