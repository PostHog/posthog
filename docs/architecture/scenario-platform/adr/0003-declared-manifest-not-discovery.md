# Topology is a declared manifest that core diffs, not discovery

Each adapter declares its processes, resources, links and valve targets in one `manifest.yaml`. Core uses that one file to:

- boot the processes;
- validate valve targets;
- draw the viewer map;
- diff it against what the run observed.

A run is `invalid` when a process is declared but not observed. A process that is observed but not declared is a warning.

We chose this over deriving the map from what the run observed. Discovery cannot tell a missing process from one that was never meant to run, and it gives the viewer nothing to draw before the first observation.

The manifest stays separate from `bin/mprocs.yaml` and phrocs for now. Generating those from manifests is a named follow-up.
