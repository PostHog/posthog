#!/bin/bash

# Widget API Testing Script
# 
# This script demonstrates how to test the widget endpoints with curl.
# Replace the placeholders with actual values from your PostHog instance.

set -e

# Configuration
API_BASE="${API_BASE:-http://localhost:8000}"
PROJECT_ID="${PROJECT_ID:-1}"
TEAM_ID="${TEAM_ID:-1}"
DISTINCT_ID="${DISTINCT_ID:-test-user-$(date +%s)}"
PUBLIC_TOKEN="${PUBLIC_TOKEN}"  # Get this from Team API or generate via endpoint

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== PostHog Conversations Widget API Test ===${NC}\n"

# Step 1: Get team configuration (requires regular auth)
echo -e "${GREEN}Step 1: Get Team Configuration${NC}"
echo "GET ${API_BASE}/api/projects/${PROJECT_ID}/environments/${TEAM_ID}/"
echo ""

if [ -z "$PUBLIC_TOKEN" ]; then
    echo -e "${RED}ERROR: PUBLIC_TOKEN not set${NC}"
    echo "Please set PUBLIC_TOKEN environment variable or generate one via:"
    echo "POST ${API_BASE}/api/projects/${PROJECT_ID}/environments/${TEAM_ID}/generate_conversations_public_token/"
    exit 1
fi

echo -e "${BLUE}Using PUBLIC_TOKEN: ${PUBLIC_TOKEN}${NC}\n"

# Step 2: Send a message (creates ticket)
echo -e "${GREEN}Step 2: Send First Message (creates ticket)${NC}"
RESPONSE=$(curl -s -X POST "${API_BASE}/api/conversations/widget/message" \
    -H "X-Conversations-Token: ${PUBLIC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"distinct_id\": \"${DISTINCT_ID}\",
        \"message\": \"Hello! I need help with my account.\",
        \"traits\": {
            \"name\": \"Test User\",
            \"email\": \"test@example.com\"
        }
    }")

echo "$RESPONSE" | python3 -m json.tool || echo "$RESPONSE"
TICKET_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['ticket_id'])" 2>/dev/null || echo "")
echo ""

if [ -z "$TICKET_ID" ]; then
    echo -e "${RED}ERROR: Failed to create ticket${NC}"
    exit 1
fi

echo -e "${BLUE}Ticket created: ${TICKET_ID}${NC}\n"

# Step 3: Send follow-up message
echo -e "${GREEN}Step 3: Send Follow-up Message${NC}"
RESPONSE=$(curl -s -X POST "${API_BASE}/api/conversations/widget/message" \
    -H "X-Conversations-Token: ${PUBLIC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"distinct_id\": \"${DISTINCT_ID}\",
        \"message\": \"I can't access my dashboard.\",
        \"ticket_id\": \"${TICKET_ID}\"
    }")

echo "$RESPONSE" | python3 -m json.tool || echo "$RESPONSE"
echo ""

# Step 4: Get messages
echo -e "${GREEN}Step 4: Get Messages for Ticket${NC}"
curl -s "${API_BASE}/api/conversations/widget/messages/${TICKET_ID}?distinct_id=${DISTINCT_ID}" \
    -H "X-Conversations-Token: ${PUBLIC_TOKEN}" \
    | python3 -m json.tool
echo ""

# Step 5: List all tickets for user
echo -e "${GREEN}Step 5: List All Tickets for User${NC}"
curl -s "${API_BASE}/api/conversations/widget/tickets?distinct_id=${DISTINCT_ID}" \
    -H "X-Conversations-Token: ${PUBLIC_TOKEN}" \
    | python3 -m json.tool
echo ""

# Step 6: Test rate limiting (send many requests)
echo -e "${GREEN}Step 6: Test Rate Limiting (expect 429 after 10 requests)${NC}"
for i in {1..12}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${API_BASE}/api/conversations/widget/message" \
        -H "X-Conversations-Token: ${PUBLIC_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{
            \"distinct_id\": \"${DISTINCT_ID}\",
            \"message\": \"Rate limit test message ${i}\",
            \"ticket_id\": \"${TICKET_ID}\"
        }")
    
    if [ "$STATUS" = "429" ]; then
        echo -e "${RED}Request ${i}: HTTP ${STATUS} (Rate limited) ✓${NC}"
        break
    else
        echo "Request ${i}: HTTP ${STATUS}"
    fi
    sleep 0.1
done
echo ""

# Step 7: Test forbidden access (wrong distinct_id)
echo -e "${GREEN}Step 7: Test Forbidden Access (wrong distinct_id)${NC}"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X GET \
    "${API_BASE}/api/conversations/widget/messages/${TICKET_ID}?distinct_id=wrong-user" \
    -H "X-Conversations-Token: ${PUBLIC_TOKEN}")

echo "$RESPONSE"
echo ""

# Step 8: Test invalid token
echo -e "${GREEN}Step 8: Test Invalid Token${NC}"
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST \
    "${API_BASE}/api/conversations/widget/message" \
    -H "X-Conversations-Token: invalid-token-12345" \
    -H "Content-Type: application/json" \
    -d "{
        \"distinct_id\": \"${DISTINCT_ID}\",
        \"message\": \"This should fail\"
    }")

echo "$RESPONSE"
echo ""

echo -e "${BLUE}=== Test Complete ===${NC}"
echo -e "Ticket ID: ${GREEN}${TICKET_ID}${NC}"
echo -e "Distinct ID: ${GREEN}${DISTINCT_ID}${NC}"

