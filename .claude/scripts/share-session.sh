#!/bin/bash
set -euo pipefail

# Get current project directory slug
PROJECT_SLUG=$(pwd | sed 's/\//-/g' | sed 's/^-//')

# Get the most recent Claude Code session log for this project
LOG_FILE=$(ls -t ~/.claude/projects/-"$PROJECT_SLUG"/*.jsonl 2>/dev/null | head -n 1)

if [ -z "$LOG_FILE" ]; then
    echo "Error: No Claude Code session logs found for project: $PROJECT_SLUG"
    echo "Checked: ~/.claude/projects/-$PROJECT_SLUG/"
    exit 1
fi

echo "Found session log: $LOG_FILE"

# Create a temporary markdown file
TEMP_MD=$(mktemp).md
SESSION_DATE=$(date -r "$LOG_FILE" "+%Y-%m-%d %H:%M:%S")

# Get custom description from arguments, or use default
DESCRIPTION="${1:-Claude Code Session - $SESSION_DATE}"

# Start markdown file with header
cat > "$TEMP_MD" << EOF
# Claude Code Session

**Date**: $SESSION_DATE
**Description**: $DESCRIPTION

---

EOF

# Parse JSONL and convert to markdown
echo "Converting session log to markdown..."

while IFS= read -r line; do
    # Extract message type
    TYPE=$(echo "$line" | jq -r '.type // empty')

    case "$TYPE" in
        "user")
            # Handle user messages
            # Check if content is a string (simple message) or array (tool results)
            CONTENT_TYPE=$(echo "$line" | jq -r '.message.content | type')

            if [ "$CONTENT_TYPE" = "string" ]; then
                # Simple user message
                CONTENT=$(echo "$line" | jq -r '.message.content')
                if [ -n "$CONTENT" ] && [ "$CONTENT" != "null" ]; then
                    echo -e "\n## User\n" >> "$TEMP_MD"
                    echo "$CONTENT" >> "$TEMP_MD"
                fi
            elif [ "$CONTENT_TYPE" = "array" ]; then
                # Tool results or complex content
                TOOL_RESULTS=$(echo "$line" | jq -r '.message.content[] | select(.type == "tool_result")')
                if [ -n "$TOOL_RESULTS" ]; then
                    # Skip tool results for now - they make the output too verbose
                    continue
                fi
            fi
            ;;
        "assistant")
            # Handle assistant messages
            echo "$line" | jq -c '.message.content[]?' | while read -r content_item; do
                CONTENT_TYPE=$(echo "$content_item" | jq -r '.type')

                case "$CONTENT_TYPE" in
                    "text")
                        TEXT=$(echo "$content_item" | jq -r '.text')
                        if [ -n "$TEXT" ] && [ "$TEXT" != "null" ]; then
                            echo -e "\n## Assistant\n" >> "$TEMP_MD"
                            echo "$TEXT" >> "$TEMP_MD"
                        fi
                        ;;
                    "tool_use")
                        TOOL_NAME=$(echo "$content_item" | jq -r '.name')
                        TOOL_INPUT=$(echo "$content_item" | jq -r '.input')
                        if [ -n "$TOOL_NAME" ] && [ "$TOOL_NAME" != "null" ]; then
                            echo -e "\n### Tool: \`$TOOL_NAME\`\n" >> "$TEMP_MD"
                            echo '```json' >> "$TEMP_MD"
                            echo "$content_item" | jq '.input' >> "$TEMP_MD"
                            echo '```' >> "$TEMP_MD"
                        fi
                        ;;
                esac
            done
            ;;
    esac
done < "$LOG_FILE"

echo "Saving session to PostHog/claude-sessions repo..."

# Generate filename with timestamp and sanitized description
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SAFE_DESC=$(echo "$DESCRIPTION" | tr ' ' '-' | tr -cd '[:alnum:]-' | cut -c1-50)
FILENAME="${TIMESTAMP}-${SAFE_DESC}.md"

# Clone or update the repo in a temp directory
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "Cloning PostHog/claude-sessions..."
if ! gh repo clone PostHog/claude-sessions 2>/dev/null; then
    echo "Error: Failed to clone PostHog/claude-sessions. Make sure you have access to the repo."
    rm -rf "$TEMP_DIR"
    rm "$TEMP_MD"
    exit 1
fi

cd claude-sessions

# Get GitHub username
GH_USERNAME=$(gh api user -q .login)
if [ -z "$GH_USERNAME" ]; then
    echo "Error: Failed to get GitHub username. Make sure you're authenticated with gh."
    cd /
    rm -rf "$TEMP_DIR"
    rm "$TEMP_MD"
    exit 1
fi

echo "Using GitHub username: $GH_USERNAME"

# Create user-specific directory
USER_DIR="sessions/$GH_USERNAME"
mkdir -p "$USER_DIR"

# Copy the markdown file
cp "$TEMP_MD" "$USER_DIR/$FILENAME"

# Commit and push
git add "$USER_DIR/$FILENAME"
git commit -m "Add Claude Code session: $DESCRIPTION

Author: $GH_USERNAME"
git push origin main

# Get the GitHub URL
SESSION_URL="https://github.com/PostHog/claude-sessions/blob/main/$USER_DIR/$FILENAME"

# Clean up
cd /
rm -rf "$TEMP_DIR"
rm "$TEMP_MD"

echo ""
echo "✓ Session log saved to PostHog/claude-sessions!"
echo "URL: $SESSION_URL"
echo ""
