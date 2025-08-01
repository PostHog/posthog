# Node Migration Plan: State Types by Graph

## InsightsAssistantGraph Nodes (should use InsightsGraphState)

### Query Generation Nodes
- `InsightRagContextNode` (from rag/nodes.py)
- `TrendsGeneratorNode` (from trends/nodes.py) 
- `TrendsGeneratorToolsNode` (from trends/nodes.py)
- `FunnelGeneratorNode` (from funnels/nodes.py)
- `FunnelGeneratorToolsNode` (from funnels/nodes.py) 
- `RetentionGeneratorNode` (from retention/nodes.py)
- `RetentionGeneratorToolsNode` (from retention/nodes.py)
- `QueryPlannerNode` (from query_planner/nodes.py)
- `QueryPlannerToolsNode` (from query_planner/nodes.py)
- `SQLGeneratorNode` (from sql/nodes.py)
- `SQLGeneratorToolsNode` (from sql/nodes.py)
- `QueryExecutorNode` (from query_executor/nodes.py)

**Current Status**: These inherit from `AssistantNode` but should inherit from `InsightsNode`
**Migration**: Update imports and class inheritance to use `InsightsNode`

## AssistantGraph Nodes (should use AssistantGraphState)

### Root & Control Nodes
- `RootNode` (from root/nodes.py)
- `RootNodeTools` (from root/nodes.py)
- `BillingNode` (from billing/nodes.py)
- `InkeepDocsNode` (from inkeep_docs/nodes.py)

### Memory Nodes  
- `MemoryOnboardingNode` (from memory/nodes.py)
- `MemoryInitializerNode` (from memory/nodes.py)
- `MemoryInitializerInterruptNode` (from memory/nodes.py)
- `MemoryOnboardingEnquiryNode` (from memory/nodes.py)
- `MemoryOnboardingEnquiryInterruptNode` (from memory/nodes.py)
- `MemoryOnboardingFinalizeNode` (from memory/nodes.py)
- `MemoryCollectorNode` (from memory/nodes.py)
- `MemoryCollectorToolsNode` (from memory/nodes.py)

### Utility Nodes
- `TitleGeneratorNode` (from title_generator/nodes.py)
- `InsightSearchNode` (from insights/nodes.py)

**Current Status**: These inherit from `AssistantNode` and should continue to do so
**Migration**: Update imports to use new `AssistantGraphState` types (already done in base.py)

## Migration Strategy

1. **Update InsightsAssistantGraph nodes first** - these need to change from `AssistantNode` to `InsightsNode`
2. **Verify AssistantGraph nodes work** - these should already work with the updated `AssistantNode` type alias
3. **Test both graphs** - ensure no runtime errors occur

## Node Files to Update for InsightsAssistantGraph

1. `ee/hogai/graph/rag/nodes.py`
2. `ee/hogai/graph/trends/nodes.py`
3. `ee/hogai/graph/funnels/nodes.py`
4. `ee/hogai/graph/retention/nodes.py` 
5. `ee/hogai/graph/query_planner/nodes.py`
6. `ee/hogai/graph/sql/nodes.py`
7. `ee/hogai/graph/query_executor/nodes.py`

## Node Files for AssistantGraph (should work as-is)

1. `ee/hogai/graph/root/nodes.py`
2. `ee/hogai/graph/billing/nodes.py`
3. `ee/hogai/graph/inkeep_docs/nodes.py`
4. `ee/hogai/graph/memory/nodes.py`
5. `ee/hogai/graph/title_generator/nodes.py`
6. `ee/hogai/graph/insights/nodes.py`