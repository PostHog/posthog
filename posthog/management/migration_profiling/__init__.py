"""
Migration profiling package for Django migrations.

Captures per-operation and per-SQL-statement wall-clock time during a
``migrate`` invocation. Emits a JSONL file consumed by the
``analyze_migration_profile`` command.
"""
