# PostHog Custom Commands

Custom Python commands for the PostHog monorepo. These extend hogli with PostHog-specific functionality that's too complex for YAML definitions.

## How It Works

This directory is loaded automatically via `config.commands_dir` in `/hogli.yaml`. Any command decorated with `@cli.command()` is registered and available via `hogli <command>`.

## Adding a Command

1. Create a new file or add to an existing one:

```python
# myfeature.py
import click
from hogli.cli import cli

@cli.command(name="my:command")
@click.option("--verbose", "-v", is_flag=True)
def my_command(verbose: bool) -> None:
    """One-line description shown in hogli --help."""
    click.echo("Done!")
```

2. Import it in `commands.py`:

```python
from . import myfeature  # noqa: F401
```

3. Test it:

```bash
hogli my:command --help
hogli my:command -v
```

## When to Use Python vs YAML

| Use Python here when... | Use YAML (`hogli.yaml`) when... |
|------------------------|--------------------------------|
| Complex logic, loops, conditionals | Simple shell one-liners |
| Need Click's argument parsing | Delegating to bin/ scripts |
| Interactive prompts or menus | Chaining existing hogli commands |
| Accessing Python libraries | Quick prototypes |

## File Structure

```
common/posthog_hogli/
├── __init__.py    # Package init (imports commands.py)
├── commands.py    # Imports all command modules
├── doctor.py      # Health/cleanup commands
└── README.md      # This file
```

## Tips

- Use `click.echo()` for output, not `print()`
- Use `click.secho(msg, fg="green")` for colored output
- Add `@click.option("--yes", "-y", is_flag=True)` for destructive commands
- Keep commands focused - compose via YAML `steps:` if needed

## See Also

- `/hogli.yaml` - YAML command definitions
- `/tools/hogli/README.md` - Framework documentation
- `/bin/` - Shell scripts (used via `bin_script:` in YAML)
