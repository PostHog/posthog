#!/usr/bin/env python3
# ruff: noqa: T201
"""
Migration Conflict Resolution Script

This script helps resolve Django migration conflicts that occur when multiple
developers create migrations in parallel branches.

Usage:
    python bin/fix-migration-conflicts.py --preview  # Show what changes would be made
    python bin/fix-migration-conflicts.py --fix      # Apply the fixes
    python bin/fix-migration-conflicts.py --app posthog --preview  # Check specific app

The script will:
1. Detect migration conflicts by comparing current branch with master
2. Find migrations in your branch that need to be renumbered
3. Update migration file names, dependencies, and max_migration.txt
"""

import os
import re
import sys
import argparse
import subprocess
from pathlib import Path
from typing import Optional
import tempfile
import shutil


class MigrationConflictResolver:
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        # Auto-detect if we're in the posthog subdirectory or project root
        if self.base_dir.name == "posthog" and (self.base_dir.parent / "billing").exists():
            self.base_dir = self.base_dir.parent

        self.apps_with_migrations = [
            "posthog/posthog",
            "billing/billing",
            "posthog/ee",
            "posthog/products/early_access_features",
            "posthog/products/user_interviews",
            # Add other apps as needed
        ]

    def run_git_command(self, cmd: list[str]) -> str:
        """Run git command and return output"""
        try:
            result = subprocess.run(["git", *cmd], capture_output=True, text=True, cwd=self.base_dir, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Git command failed: {' '.join(cmd)}")
            print(f"Error: {e.stderr}")
            sys.exit(1)

    def get_current_branch(self) -> str:
        """Get current branch name"""
        try:
            return self.run_git_command(["branch", "--show-current"])
        except:
            # Fallback for detached HEAD
            return self.run_git_command(["rev-parse", "HEAD"])

    def get_migration_number(self, filename: str) -> Optional[int]:
        """Extract migration number from filename"""
        match = re.match(r"(\d+)_.*\.py$", filename)
        return int(match.group(1)) if match else None

    def parse_migration_dependencies(self, filepath: Path) -> list[str]:
        """Parse dependencies from migration file"""
        try:
            with open(filepath) as f:
                content = f.read()

            # Find dependencies array
            deps_match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
            if not deps_match:
                return []

            deps_content = deps_match.group(1)
            # Extract dependency tuples like ("posthog", "0782_some_migration")
            deps = re.findall(r'\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)', deps_content)
            return [f"{app}.{migration}" for app, migration in deps]
        except Exception as e:
            print(f"Warning: Could not parse dependencies from {filepath}: {e}")
            return []

    def update_migration_dependencies(self, filepath: Path, old_dep: str, new_dep: str) -> None:
        """Update dependencies in migration file"""
        try:
            with open(filepath) as f:
                content = f.read()

            # Replace the old dependency with new one
            app_name, old_migration = old_dep.split(".", 1)
            app_name_new, new_migration = new_dep.split(".", 1)

            # Update the dependency tuple
            old_pattern = f'("{app_name}", "{old_migration}")'
            new_pattern = f'("{app_name_new}", "{new_migration}")'

            content = content.replace(old_pattern, new_pattern)

            # Also handle single quotes
            old_pattern = f"('{app_name}', '{old_migration}')"
            new_pattern = f"('{app_name_new}', '{new_migration}')"
            content = content.replace(old_pattern, new_pattern)

            with open(filepath, "w") as f:
                f.write(content)
        except Exception as e:
            print(f"Error updating dependencies in {filepath}: {e}")

    def get_app_migrations(self, app_path: str, ref: str = "HEAD") -> dict[str, str]:
        """Get migration files for an app at a specific git ref"""
        migrations_dir = f"{app_path}/migrations"
        try:
            # Get list of files at the ref
            files = self.run_git_command(["ls-tree", "--name-only", f"{ref}:{migrations_dir}"])
            migrations = {}
            for file in files.split("\n"):
                if file.endswith(".py") and re.match(r"\d+_.*\.py$", file):
                    migration_num = self.get_migration_number(file)
                    if migration_num is not None:
                        migrations[migration_num] = file
            return migrations
        except:
            return {}

    def get_max_migration_number(self, app_path: str, ref: str = "HEAD") -> int:
        """Get the highest migration number for an app at a specific ref"""
        migrations = self.get_app_migrations(app_path, ref)
        return max(migrations.keys()) if migrations else 0

    def read_max_migration_file(self, app_path: str, ref: str = "HEAD") -> Optional[str]:
        """Read max_migration.txt content at a specific ref"""
        max_migration_path = f"{app_path}/migrations/max_migration.txt"
        try:
            content = self.run_git_command(["show", f"{ref}:{max_migration_path}"])
            return content.strip()
        except:
            return None

    def detect_conflicts(self, app_filter: Optional[str] = None) -> dict[str, dict]:
        """Detect migration conflicts between current branch and master"""
        current_branch = self.get_current_branch()
        conflicts = {}

        print(f"Checking for migration conflicts between '{current_branch}' and 'origin/master'...")

        # First, fetch latest master
        self.run_git_command(["fetch", "origin", "master"])

        apps_to_check = self.apps_with_migrations
        if app_filter:
            apps_to_check = [app for app in apps_to_check if app_filter in app]

        for app_path in apps_to_check:
            print(f"\nChecking app: {app_path}")

            # Get migrations on master and current branch
            master_migrations = self.get_app_migrations(app_path, "origin/master")
            current_migrations = self.get_app_migrations(app_path, "HEAD")

            # Find migrations that exist in current branch but not in master
            current_only = set(current_migrations.keys()) - set(master_migrations.keys())
            master_only = set(master_migrations.keys()) - set(current_migrations.keys())

            if current_only and master_only:
                # There's a conflict - we have migrations in both branches with different numbers
                max_master = max(master_migrations.keys()) if master_migrations else 0
                max_current = max(current_migrations.keys()) if current_migrations else 0

                conflicts[app_path] = {
                    "master_migrations": master_migrations,
                    "current_migrations": current_migrations,
                    "current_only": current_only,
                    "master_only": master_only,
                    "max_master": max_master,
                    "max_current": max_current,
                    "master_max_migration_txt": self.read_max_migration_file(app_path, "origin/master"),
                    "current_max_migration_txt": self.read_max_migration_file(app_path, "HEAD"),
                }

                print(f"  ⚠️  CONFLICT DETECTED!")
                print(f"  Master has migrations up to: {max_master}")
                print(f"  Current branch has migrations: {sorted(current_only)}")
                print(f"  Master has new migrations: {sorted(master_only)}")
            else:
                print(f"  ✅ No conflicts detected")

        return conflicts

    def preview_fixes(self, conflicts: dict[str, dict]) -> dict[str, list]:
        """Preview what changes would be made to fix conflicts"""
        if not conflicts:
            print("\n✅ No conflicts to fix!")
            return {}

        changes = {}

        print("\n" + "=" * 60)
        print("PREVIEW OF CHANGES TO FIX MIGRATION CONFLICTS")
        print("=" * 60)

        for app_path, conflict in conflicts.items():
            print(f"\n📁 App: {app_path}")
            print("-" * 40)

            app_changes = []
            current_only = sorted(conflict["current_only"])
            max_master = conflict["max_master"]

            # Calculate new migration numbers
            new_numbers = {}
            next_num = max_master + 1

            for old_num in current_only:
                new_numbers[old_num] = next_num
                next_num += 1

            # Plan file renames
            for old_num in current_only:
                old_file = conflict["current_migrations"][old_num]
                new_num = new_numbers[old_num]
                new_file = old_file.replace(f"{old_num:04d}_", f"{new_num:04d}_")

                app_changes.append(
                    {
                        "type": "rename_file",
                        "old_path": f"{app_path}/migrations/{old_file}",
                        "new_path": f"{app_path}/migrations/{new_file}",
                        "old_num": old_num,
                        "new_num": new_num,
                    }
                )

                print(f"  📝 RENAME: {old_file} → {new_file}")

            # Plan dependency updates
            for old_num in current_only:
                old_file = conflict["current_migrations"][old_num]
                migration_path = self.base_dir / app_path / "migrations" / old_file

                if migration_path.exists():
                    deps = self.parse_migration_dependencies(migration_path)
                    for dep in deps:
                        if "." in dep:
                            dep_app, dep_migration = dep.split(".", 1)
                            dep_num = self.get_migration_number(dep_migration + ".py")

                            if dep_num in new_numbers:
                                new_dep_num = new_numbers[dep_num]
                                new_dep_migration = dep_migration.replace(f"{dep_num:04d}_", f"{new_dep_num:04d}_")

                                app_changes.append(
                                    {
                                        "type": "update_dependency",
                                        "file": f"{app_path}/migrations/{old_file}",
                                        "old_dep": dep,
                                        "new_dep": f"{dep_app}.{new_dep_migration}",
                                    }
                                )

                                print(f"  🔗 UPDATE DEPENDENCY in {old_file}:")
                                print(f"     {dep} → {dep_app}.{new_dep_migration}")

            # Plan max_migration.txt update
            if current_only:
                highest_new_num = max(new_numbers.values())
                highest_new_file = None
                for old_num, new_num in new_numbers.items():
                    if new_num == highest_new_num:
                        old_file = conflict["current_migrations"][old_num]
                        highest_new_file = old_file.replace(f"{old_num:04d}_", f"{new_num:04d}_").replace(".py", "")
                        break

                if highest_new_file:
                    app_changes.append(
                        {
                            "type": "update_max_migration",
                            "file": f"{app_path}/migrations/max_migration.txt",
                            "new_content": highest_new_file,
                        }
                    )

                    print(f"  📄 UPDATE max_migration.txt: {highest_new_file}")

            changes[app_path] = app_changes

        return changes

    def apply_fixes(self, changes: dict[str, list]) -> None:
        """Apply the fixes based on the planned changes"""
        if not changes:
            print("\n✅ No changes to apply!")
            return

        print("\n" + "=" * 60)
        print("APPLYING MIGRATION CONFLICT FIXES")
        print("=" * 60)

        for app_path, app_changes in changes.items():
            print(f"\n📁 Fixing app: {app_path}")

            # Create backup
            backup_dir = self.create_backup(app_path)
            print(f"  💾 Created backup at: {backup_dir}")

            try:
                # Apply changes in order: renames first, then dependency updates, then max_migration.txt
                renames = [c for c in app_changes if c["type"] == "rename_file"]
                dep_updates = [c for c in app_changes if c["type"] == "update_dependency"]
                max_updates = [c for c in app_changes if c["type"] == "update_max_migration"]

                # 1. Rename files
                for change in renames:
                    old_path = self.base_dir / change["old_path"]
                    new_path = self.base_dir / change["new_path"]
                    if old_path.exists():
                        shutil.move(str(old_path), str(new_path))
                        print(f"  ✅ Renamed: {change['old_path']} → {change['new_path']}")

                # 2. Update dependencies
                for change in dep_updates:
                    file_path = self.base_dir / change["file"]
                    # Update the file path if it was renamed
                    for rename in renames:
                        if change["file"] == rename["old_path"]:
                            file_path = self.base_dir / rename["new_path"]
                            break

                    if file_path.exists():
                        self.update_migration_dependencies(file_path, change["old_dep"], change["new_dep"])
                        print(f"  ✅ Updated dependency in: {file_path.name}")

                # 3. Update max_migration.txt
                for change in max_updates:
                    max_file = self.base_dir / change["file"]
                    if max_file.parent.exists():
                        with open(max_file, "w") as f:
                            f.write(change["new_content"] + "\n")
                        print(f"  ✅ Updated: {change['file']}")

                print(f"  🎉 Successfully fixed conflicts in {app_path}")

            except Exception as e:
                print(f"  ❌ Error fixing {app_path}: {e}")
                print(f"  🔄 Restoring from backup...")
                self.restore_backup(app_path, backup_dir)
                raise

    def create_backup(self, app_path: str) -> str:
        """Create a backup of the migrations directory"""
        migrations_dir = self.base_dir / app_path / "migrations"
        if not migrations_dir.exists():
            return ""

        backup_dir = tempfile.mkdtemp(prefix=f"migration_backup_{app_path.replace('/', '_')}_")
        shutil.copytree(str(migrations_dir), f"{backup_dir}/migrations")
        return backup_dir

    def restore_backup(self, app_path: str, backup_dir: str) -> None:
        """Restore from backup"""
        if not backup_dir or not os.path.exists(backup_dir):
            return

        migrations_dir = self.base_dir / app_path / "migrations"
        if migrations_dir.exists():
            shutil.rmtree(str(migrations_dir))

        shutil.copytree(f"{backup_dir}/migrations", str(migrations_dir))
        shutil.rmtree(backup_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Fix Django migration conflicts between branches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview changes for all apps
  python bin/fix-migration-conflicts.py --preview

  # Apply fixes for all apps
  python bin/fix-migration-conflicts.py --fix

  # Check only posthog app
  python bin/fix-migration-conflicts.py --app posthog --preview

  # Apply fixes only for posthog app
  python bin/fix-migration-conflicts.py --app posthog --fix
        """,
    )

    parser.add_argument("--preview", action="store_true", help="Show what changes would be made without applying them")

    parser.add_argument("--fix", action="store_true", help="Apply the migration conflict fixes")

    parser.add_argument("--app", help='Only check specific app (e.g., "posthog", "billing")')

    args = parser.parse_args()

    if not args.preview and not args.fix:
        parser.error("Must specify either --preview or --fix")

    if args.preview and args.fix:
        parser.error("Cannot specify both --preview and --fix")

    resolver = MigrationConflictResolver()

    # Detect conflicts
    conflicts = resolver.detect_conflicts(app_filter=args.app)

    if args.preview:
        changes = resolver.preview_fixes(conflicts)
        if changes:
            print(f"\n💡 To apply these fixes, run:")
            cmd = "python bin/fix-migration-conflicts.py --fix"
            if args.app:
                cmd += f" --app {args.app}"
            print(f"   {cmd}")

    elif args.fix:
        if not conflicts:
            print("\n✅ No conflicts detected, nothing to fix!")
            return

        print(f"\n⚠️  About to fix migration conflicts. This will:")
        print("   • Rename migration files")
        print("   • Update migration dependencies")
        print("   • Update max_migration.txt files")
        print("   • Create backups of original files")

        response = input("\n❓ Continue? [y/N]: ")
        if response.lower() != "y":
            print("Cancelled.")
            return

        changes = resolver.preview_fixes(conflicts)
        resolver.apply_fixes(changes)

        print("\n🎉 Migration conflicts fixed!")
        print("💡 Don't forget to:")
        print("   • Review the changes with 'git diff'")
        print("   • Test your migrations")
        print("   • Commit the fixes")


if __name__ == "__main__":
    main()
