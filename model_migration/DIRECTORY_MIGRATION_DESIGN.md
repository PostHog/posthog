# Directory-Based Migration Design

## Problem

Current file-based approach requires listing every file individually:

```json
{
  "source_files": [
    "external_data_source.py",
    "external_data_job.py",
    "datawarehouse_saved_query.py",
    ...
  ]
}
```

For `posthog/warehouse/` with 47 Python files across multiple subdirectories, this is tedious and error-prone.

## Solution: Convention Over Configuration

Enable moving entire directory structures automatically with minimal config.

**Status**: ✅ IMPLEMENTED in `migrate_models.py`

### Simplified Config

**Before** (file-based - tedious):

```json
{
  "name": "data_warehouse",
  "source_files": [
    "external_data_source.py",
    "external_data_job.py",
    ...  // 12 files listed manually
  ],
  "source_base_path": "posthog/warehouse/models",
  "target_app": "data_warehouse"
}
```

**After** (directory-based - automatic):

```json
{
    "name": "data_warehouse_complete",
    "source_base_path": "posthog/warehouse",
    "target_app": "data_warehouse",
    "move_entire_directory": true,
    "merge_models": false
}
```

No `source_files` needed! Script scans directory automatically.

### Auto-Detection Rules

When `move_entire_directory: true`:

1. **Scan subdirectories** in `source_base_path`
2. **Apply convention-based mapping**:

| Source                         | Target                                       | Special Handling             |
| ------------------------------ | -------------------------------------------- | ---------------------------- |
| `posthog/warehouse/models/`    | `products/data_warehouse/backend/models/`    | ✅ Model-specific operations |
| `posthog/warehouse/api/`       | `products/data_warehouse/backend/api/`       | Import updates only          |
| `posthog/warehouse/data_load/` | `products/data_warehouse/backend/data_load/` | Import updates only          |
| `posthog/warehouse/test/`      | `products/data_warehouse/backend/test/`      | Import updates only          |
| `posthog/warehouse/api/test/`  | `products/data_warehouse/backend/api/test/`  | Import updates only          |
| `posthog/warehouse/*.py`       | `products/data_warehouse/backend/`           | Import updates only          |

3. **Model-specific operations** (only for `models/` subdirectory):
    - Inject `db_table = "posthog_modelname"` Meta attribute
    - Move admin classes
    - Update ForeignKey references
    - Generate Django migrations

4. **Import updates** (all files):
    - Use LibCST to transform imports
    - Respect `merge_models` setting for models directory
    - Use file-specific imports for other directories

### Example: posthog/warehouse/

**Directory structure**:

```text
posthog/warehouse/
├── models/              # 12 model files (already migrated ✓)
├── api/                 # 12 API files
│   └── test/           # 14 test files
├── data_load/          # 4 service files
│   └── test/           # 1 test file
├── external_data_source/
│   └── jobs.py
├── hogql.py
├── s3.py
└── types.py
```

**Migration result**:

```text
products/data_warehouse/backend/
├── models/              # From posthog/warehouse/models/ ✓
├── api/                 # From posthog/warehouse/api/
│   └── test/           # From posthog/warehouse/api/test/
├── data_load/          # From posthog/warehouse/data_load/
│   └── test/           # From posthog/warehouse/data_load/test/
├── hogql.py            # From posthog/warehouse/hogql.py
├── s3.py               # From posthog/warehouse/s3.py
└── types.py            # From posthog/warehouse/types.py
```

**Excluded** (via `exclude_subdirs`):

```text
posthog/warehouse/external_data_source/jobs.py  # Not migrated
```

## Implementation Details

### Phase 1: Add Directory Mode Support ✅

1. ✅ Added `move_entire_directory` flag to config schema
2. ✅ Implemented `_scan_directory_for_files()` in `migrate_models.py` (lines 243-282)
3. ✅ Modified `migrate_models()` to auto-scan when flag is set (lines 1713-1720)

### Phase 2: Subdirectory-Specific Handling ✅

1. ✅ `models/` subdirectory detection → Already handled by existing `_expand_subdirectory_files()`
2. ✅ Other subdirectories → Existing code moves files + updates imports
3. ✅ Nested test directories (`api/test/`) → Handled by recursive scanning

### Phase 3: Import Path Updates ✅

1. ✅ `ImportTransformer` already handles subdirectory imports via pattern matching
2. ✅ Preserves subdirectory structure in imports automatically

### Key Implementation Functions

1. **`_scan_directory_for_files(source_base_path)`** (new)
    - Recursively scans directory for all `.py` files
    - Skips `__pycache__` and `__init__.py`
    - Returns relative paths sorted

2. **`migrate_models(migration_spec)`** (modified)
    - Checks for `move_entire_directory` flag
    - If true, calls `_scan_directory_for_files()` instead of using `source_files`
    - Otherwise uses existing file-based approach

3. **Existing functions handle the rest**:
    - `_expand_subdirectory_files()` - Groups files by subdirectory
    - `_move_model_files_no_merge_mode()` - Preserves directory structure
    - `_update_imports_for_module()` - Updates imports for each module

## Benefits

1. **Less config**: Single directory instead of 47 file paths
2. **Convention-based**: Predictable behavior without explicit rules
3. **Maintains structure**: Preserves logical organization (api/, data_load/, test/)
4. **Selective operations**: Model-specific operations only where needed
5. **Flexible**: Can still exclude specific subdirectories if needed

## Migration for Remaining warehouse/ Files

**Current state**:

- ✅ `posthog/warehouse/models/` → Already migrated (12 files)

**Remaining** (35 files):

- `api/` → 12 files
- `api/test/` → 14 files
- `data_load/` → 4 files
- `data_load/test/` → 1 file
- Top-level → 4 files (hogql.py, s3.py, types.py, **init**.py)

**With directory mode**:

```json
{
    "name": "data_warehouse_remaining",
    "source_base_path": "posthog/warehouse",
    "target_app": "data_warehouse",
    "move_entire_directory": true,
    "exclude_subdirs": ["models", "external_data_source"]
}
```

This single config handles all 35 remaining files with correct subdirectory placement.
