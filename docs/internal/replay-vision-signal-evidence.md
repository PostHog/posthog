# Replay Vision signal timestamps

New signals responses require nonnegative whole-second timestamps with `start_time <= end_time`.
Each finding must end at or before the recording duration. A duration of 10.9 seconds permits `REC_T 10`, but not `REC_T 11`.
Equal start and end times are valid, including zero in a recording shorter than one second.

A nonempty response fails validation when the recording duration is missing, nonfinite, zero, or negative.
An empty signals list is valid regardless of duration.

If any finding fails validation, the provider gets one correction request for the signals response.
For timestamps past the duration, the request says to use visible timestamps or omit the finding, without clamping timestamps.
For an unavailable duration, the request says to return an empty signals list.
If the second response also fails, the signals step contributes no findings. The main scanner output is preserved.

Time ordering is validated on `SignalsResponse`, not the shared `SignalFinding` payload.
Stored `ScannerCallOutput` payloads can still load legacy findings whose end time precedes their start time.
