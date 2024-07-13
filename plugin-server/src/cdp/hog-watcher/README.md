# How this whole thing works

The HogWatcher is a class that is responsible for monitoring the health of the hog functions.
Generally we want to make "observations" about the health of a function and then based on those observations we can determine the "state" of the function.
Observations are made per-consumer and then aggregated by the leader to determine the state of the function.

Each Watcher only needs to worry about the current state of any functions it is processing. The observations are only really interesting to the leader, as it
is the one that will be making the decisions about the state of the function.

# Rating system

We want to detect when a function has gone rogue and gradually stop it from running.
We calculate its "rating" based on how many times it has succeeded and failed.

-   If the rating falls too low, over a period of time we want to move it to the overflow queue as a first step to ensure it doesn't hog resources.
-   If it stays too low, we eventually want to disable it for a period of time.
-   If it _still_ behaves poorly after this time period, we want to disable it indefinitely.

This can be represented as a state for the function - 1. Healthy, 2. Overflowed, 3. Disabled for a period, 4. Disabled indefinitely.

To be able to do this right we need to store an array of values for the functions rating over time that represent the last say 10 minutes.

In addition we need to record the last N states of the function so that we can decide to disable it indefinitely if it has spent too much time in state 3

-   State 1:
    -   If the rating average over the time period is below 0.5, move to state 2.
-   State 2:
    -   If the rating average over the time period is above 0.5, move to state 1.
    -   If the rating average over the time period is below 0.5 AND the function was in state 3 for more than N of the last states, move to state 4.
    -   If the rating average over the time period is below 0.5, move to state 3.
-   State 3:
    -   The function is disabled for a period of time (perhaps the same as the measuring period).
    -   Once it is out of this masked period, move to state 2.
-   State 4:
    -   The function is disabled and requires manual intervention

# Leader specific work

To simplify an already relatively complex concept, there is one leader who is responsible for making sure the persisted state is efficient and up-to-date.
It is also responsible for calculating state changes, persisting them to redis and emitting to other consumers.

The state is kept in one redis @hash with keys like this:

```js
{
    "states": `[["a", 1], ["b", 2]]`,
    "FUNCTION_ID:states": `[{ t: 1, s: 0.5 }]`,
    "FUNCTION_ID:ratings": `[{ t: 1, r: 0.9 }]`,
    "FUNCTION_ID:observation:observerID:periodTimestamp": `[{ s: 1, f: 2, as: 0, af: 1 }]`
}
```

Whenever an observation is made, it is persisted to a temporary key `FUNCTION_ID:observation:observerID:timestamp` and emitted. This allows the leader to load it from redis on startup as well as react to the emitted value, whichever it does first.
Periodically it merges all observations together and when a finally rating is calculated it persists just the rating (to save on space).

At the same time as compacting the ratings, it checks for any state changes and updates the relevant state key.

This is designed to keep the workers lightweight, only having to worry about their own observations and keeping a list of states in memory. Only the leader has to keep the whole object in memory.
