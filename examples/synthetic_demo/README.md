# Synthetic Demo (not for production)

This folder is a **demonstration only**. It contains a self-contained script
that generates synthetic (fake) product-analytics events plus a sample CSV of
its output.

- `generate_events.py` — deterministic generator producing fake events.
- `sample_events.csv` — example output committed for illustration.
- `test_generate_events.py` — sanity checks for the generator.

Nothing here connects to the PostHog application, a database, or any real
user data. It exists purely to demonstrate a pull request end-to-end.

## Usage

```bash
python3 examples/synthetic_demo/generate_events.py
```
