# PostHog hogli Commands

This folder contains PostHog-specific custom commands for hogli.

The hogli framework lives in `tools/hogli/`. Command definitions are in `hogli.yaml` at the repo root.

## Structure

```
common/posthog_hogli/
├── commands.py   # Entry point, imports other modules
└── doctor.py     # Health check commands (doctor:disk)
```

## Adding Custom Commands

1. Create a new file (e.g., `mycommands.py`):

```python
import click
from hogli.cli import cli

@cli.command(name="my:thing")
@click.option("--verbose", is_flag=True)
def my_thing(verbose: bool) -> None:
    """Does something useful."""
    click.echo("Hello!")
```

2. Import it in `commands.py`:

```python
from . import mycommands  # noqa: F401
```

## Configuration

The `config.commands_dir` in `hogli.yaml` points here:

```yaml
config:
    commands_dir: common/posthog_hogli
```

## When to Use Python Commands vs YAML

**Use Python commands (`common/posthog_hogli/`) when:**
- Need complex logic, loops, or conditionals in Python
- Want Click's argument parsing and validation
- Building interactive workflows

**Use YAML commands (`hogli.yaml`) when:**
- Simple shell one-liners (`cmd:`)
- Delegating to bin scripts (`bin_script:`)
- Orchestrating other hogli commands (`steps:`)

See `tools/hogli/README.md` for full framework documentation.
