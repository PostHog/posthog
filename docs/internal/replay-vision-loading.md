# Replay Vision loading

Observation pages load the result independently of the recording player component. The component loads when the reader expands the recording or selects a citation. Playback remains paused on manual expansion. A citation seeks after the recording data is ready.

Observation detail requests omit `order_by=-created_at`, which is the API default. This permits the indexed previous/next lookup when no other filters apply. Other sorting and filter parameters remain unchanged.

Scanner pages load observation rows when the Observations table mounts. Leaving the table stops automatic row refreshes. Returning reloads the rows with the current filters and sort. Statistics still load for scanner warnings, including while another tab is open.

Search, On-demand, Backfills, Configuration, Calibration, Scouts, and Alerts load their components when selected. Tab controls remain available while a tab loads. These imports use the shared chunk retry and error recovery behavior.

To check loading performance, compare cold and warm navigation separately. Measure time until the observation result or selected tab is usable. Check JavaScript requests separately from API response times. A smaller initial dependency graph does not prove a reduction in API latency.
