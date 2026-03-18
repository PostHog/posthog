#!/bin/bash

# Script to create a new PostHog notebook node
# Usage: ./bin/create-notebook-node.sh

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Ask for node name
echo -e "${BLUE}Creating a new PostHog notebook node${NC}"
echo ""
read -p "Enter the node name (PascalCase, e.g., 'RelatedGroups'): " NODE_NAME

if [ -z "$NODE_NAME" ]; then
    echo "Error: Node name cannot be empty"
    exit 1
fi

# Convert PascalCase to kebab-case for the node type
# e.g., RelatedGroups -> related-groups
NODE_TYPE=$(echo "$NODE_NAME" | sed 's/\([A-Z]\)/-\1/g' | sed 's/^-//' | tr '[:upper:]' '[:lower:]')
NODE_TYPE="ph-$NODE_TYPE"

# Ask for human-readable label
echo ""
read -p "Enter the human-readable label (e.g., 'Related groups'): " NODE_LABEL

if [ -z "$NODE_LABEL" ]; then
    echo "Error: Node label cannot be empty"
    exit 1
fi

echo ""
echo -e "${GREEN}Creating notebook node:${NC}"
echo "  Node name: $NODE_NAME"
echo "  Node type: $NODE_TYPE"
echo "  Label: $NODE_LABEL"
echo ""

# Define file paths
NODES_DIR="$PROJECT_ROOT/frontend/src/scenes/notebooks/Nodes"
NODE_FILE="$NODES_DIR/NotebookNode$NODE_NAME.tsx"
EDITOR_FILE="$PROJECT_ROOT/frontend/src/scenes/notebooks/Notebook/Editor.tsx"
TYPES_FILE="$PROJECT_ROOT/frontend/src/scenes/notebooks/types.ts"
FILTER_FILE="$PROJECT_ROOT/frontend/src/scenes/notebooks/NotebooksTable/ContainsTypeFilter.tsx"
UTILS_FILE="$PROJECT_ROOT/frontend/src/scenes/notebooks/utils.ts"

# Step 1: Create the node component file
echo -e "${BLUE}1. Creating node component file...${NC}"

cat > "$NODE_FILE" << 'EOF'
import { useValues } from 'kea'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNode__NODE_NAME__Attributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)

    if (!expanded) {
        return null
    }

    return (
        <div className="p-4">
            {/* TODO: Implement component */}
            <p>__NODE_NAME__ component - implement your UI here</p>
        </div>
    )
}

type NotebookNode__NODE_NAME__Attributes = {
    // TODO: Add your attributes here
}

export const NotebookNode__NODE_NAME__ = createPostHogWidgetNode<NotebookNode__NODE_NAME__Attributes>({
    nodeType: NotebookNodeType.__NODE_NAME__,
    titlePlaceholder: '__TITLE_PLACEHOLDER__',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        // TODO: Add your attribute definitions here
    },
})
EOF

# Replace placeholders
sed -i '' "s/__NODE_NAME__/$NODE_NAME/g" "$NODE_FILE"
sed -i '' "s/__TITLE_PLACEHOLDER__/$NODE_LABEL/g" "$NODE_FILE"

echo "  Created: $NODE_FILE"

# Step 2: Add import and extension to Editor.tsx
echo -e "${BLUE}2. Updating Editor.tsx...${NC}"

# Add import statement after the last NotebookNode import
IMPORT_LINE="import { NotebookNode$NODE_NAME } from '../Nodes/NotebookNode$NODE_NAME'"
LAST_IMPORT_LINE=$(grep -n "^import { NotebookNode" "$EDITOR_FILE" | tail -1 | cut -d: -f1)

# Use awk to insert the import line
awk -v line="$LAST_IMPORT_LINE" -v text="$IMPORT_LINE" 'NR==line{print; print text; next}1' "$EDITOR_FILE" > "$EDITOR_FILE.tmp" && mv "$EDITOR_FILE.tmp" "$EDITOR_FILE"

# Add the node to the extensions array (after the last node, before the closing bracket)
# Find the line with the closing bracket of the extensions array
EXTENSIONS_CLOSE=$(grep -n "^    \]$" "$EDITOR_FILE" | head -1 | cut -d: -f1)

# Use awk to insert the extension line before the closing bracket
awk -v line="$EXTENSIONS_CLOSE" -v text="        NotebookNode$NODE_NAME," 'NR==line{print text; print; next}1' "$EDITOR_FILE" > "$EDITOR_FILE.tmp" && mv "$EDITOR_FILE.tmp" "$EDITOR_FILE"

echo "  Updated: $EDITOR_FILE"

# Step 3: Add to NotebookNodeType enum
echo -e "${BLUE}3. Updating NotebookNodeType enum...${NC}"

ENUM_LINE=$(grep -n "ZendeskTickets = 'ph-zendesk-tickets'," "$TYPES_FILE" | cut -d: -f1)

# Use awk to insert the enum entry
awk -v line="$ENUM_LINE" -v text="    $NODE_NAME = '$NODE_TYPE'," 'NR==line{print; print text; next}1' "$TYPES_FILE" > "$TYPES_FILE.tmp" && mv "$TYPES_FILE.tmp" "$TYPES_FILE"

echo "  Updated: $TYPES_FILE"

# Step 4: Add to fromNodeTypeToLabel
echo -e "${BLUE}4. Updating ContainsTypeFilter.tsx...${NC}"

FILTER_LINE=$(grep -n "\[NotebookNodeType.ZendeskTickets\]: 'Zendesk tickets'," "$FILTER_FILE" | cut -d: -f1)

# Use awk to insert the filter entry
awk -v line="$FILTER_LINE" -v text="    [NotebookNodeType.$NODE_NAME]: '$NODE_LABEL'," 'NR==line{print; print text; next}1' "$FILTER_FILE" > "$FILTER_FILE.tmp" && mv "$FILTER_FILE.tmp" "$FILTER_FILE"

echo "  Updated: $FILTER_FILE"

# Step 5: Add to customNodeTextSerializers
echo -e "${BLUE}5. Updating utils.ts...${NC}"

UTILS_LINE=$(grep -n "\[NotebookNodeType.ZendeskTickets\]: customOrTitleSerializer," "$UTILS_FILE" | cut -d: -f1)

# Use awk to insert the serializer entry
awk -v line="$UTILS_LINE" -v text="        [NotebookNodeType.$NODE_NAME]: customOrTitleSerializer," 'NR==line{print; print text; next}1' "$UTILS_FILE" > "$UTILS_FILE.tmp" && mv "$UTILS_FILE.tmp" "$UTILS_FILE"

echo "  Updated: $UTILS_FILE"

echo ""
echo -e "${GREEN}✓ Successfully created notebook node: $NODE_NAME${NC}"
echo ""
echo "Next steps:"
echo "  1. Implement the component in: $NODE_FILE"
echo "  2. Define the attributes for your node"
echo "  3. Add any custom settings if needed"
echo "  4. Test your new node in a notebook"
echo ""