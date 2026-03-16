# Developer Environment

Configuration for the local developer environment, driving `hogli dev:setup` and the mprocs-based process manager.

Uses an **intent → capability → process** model: pick what you're working on, and only the relevant services start. See `intent-map.yaml` for the full mapping. Process definitions live in `bin/mprocs.yaml`.
