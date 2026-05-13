"""Console entry point — delegates to the click CLI in backend/cli.py."""

from products.automl.backend.cli import cli


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
