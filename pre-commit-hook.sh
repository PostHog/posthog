#!/bin/bash

# Git pre-commit hook to warn about editing models that are no longer managed by Django migrations
# These models have their schemas managed in rust/persons-migrator instead

# Define the models that are managed outside of Django
UNMANAGED_MODELS=(
    "person"
    "persondistinctid"
    "personlessdistinctid"
    "personoverridemapping"
    "personoverride"
    "pendingpersonoverride"
    "flatpersonoverride"
    "featureflaghashkeyoverride"
    "cohortpeople"
    "group"
    "grouptypemapping"
)

# Files that contain these models
MODEL_FILES=(
    "posthog/models/person/person.py"
    "posthog/models/group/group.py"
    "posthog/models/group_type_mapping.py"
    "posthog/models/cohort/cohort.py"
    "posthog/models/feature_flag/feature_flag.py"
)

# Check if any of the model files are being committed
MODIFIED_MODEL_FILES=""
for file in "${MODEL_FILES[@]}"; do
    if git diff --cached --name-only | grep -q "^${file}$"; then
        MODIFIED_MODEL_FILES="${MODIFIED_MODEL_FILES}${file}\n"
    fi
done

# If model files were modified, show warning
if [ -n "$MODIFIED_MODEL_FILES" ]; then
    echo ""
    echo "⚠️  WARNING: You are modifying Django models that are NO LONGER managed by Django migrations!"
    echo ""
    echo "The following files contain models whose database schemas are now managed outside of Django:"
    echo -e "$MODIFIED_MODEL_FILES"
    echo ""
    echo "These models are listed in posthog/person_db_router.py and include:"
    for model in "${UNMANAGED_MODELS[@]}"; do
        echo "  - $model"
    done
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  IMPORTANT: Any schema changes to these models MUST be made in:"
    echo "   rust/persons-migrator"
    echo ""
    echo "Django migrations will NOT be generated or applied for these models!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Do you want to continue with the commit? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Commit aborted."
        exit 1
    fi
fi

# Continue with the commit
exit 0