# Survey AI Research Assistant - Project Documentation

**Status**: 🟡 PLANNING COMPLETE - READY FOR IMPLEMENTATION  
**Last Updated**: 2025-01-25  
**Next Step**: Begin backend MaxTool implementation

## Project Overview

Create a MaxTool that acts as a research assistant for PostHog Surveys, enabling users to analyze survey responses and extract actionable insights from open-ended questions.

### Primary Goal
Enable Survey users to summarize their survey responses into actionable insights with great signal-to-noise ratio, focusing initially on **summarizing all open-ended questions**.

### Future Capabilities Identified
- Cross-reference responses with user properties/segments  
- Trend analysis over time
- Sentiment analysis of feedback
- Actionable insight generation with recommendations
- Categorization of feedback themes
- Integration with other PostHog data (events, user properties)

---

## Current System Analysis

### Existing Survey Response Processing
The system already has sophisticated response processing in `frontend/src/scenes/surveys/surveyLogic.tsx`:

- **`consolidatedSurveyResults`**: Loader that fetches and processes all survey responses
- **`processResultsForSurveyQuestions()`**: Function that processes raw responses into structured data
- **Response Types**: 
  - `OpenQuestionProcessedResponses`: Individual text responses with person data
  - `ChoiceQuestionProcessedResponses`: Aggregated choice data with person information

### Open-Ended Content Sources

**1. Pure Open Questions** (`SurveyQuestionType.Open`)
- Source: `OpenQuestionProcessedResponses.data[]`
- Extract: `item.response` (the text response)
- Includes: `distinctId`, `personProperties`, `timestamp`

**2. Choice Questions with Open Input** (`hasOpenChoice: true`)
- Source: `ChoiceQuestionProcessedResponses.data[]` 
- Filter: `item.isPredefined === false` ✨ **KEY INSIGHT**
- Extract: `item.label` (this IS the custom text response)
- Works for both SingleChoice and MultipleChoice questions
- Includes person data when available

### MaxTool Infrastructure
- Existing pattern established in `products/surveys/backend/max_tools.py`
- `CreateSurveyTool` already implemented for survey creation
- Well-established evaluation framework in `ee/hogai/eval/`

---

## Implementation Plan

### Phase 1: Backend MaxTool Implementation

**File**: `products/surveys/backend/max_tools.py` (extend existing file)

**New Classes to Add**:
```python
class SurveyAnalysisArgs(BaseModel):
    survey_id: str = Field(description="ID of the survey to analyze")
    question_ids: Optional[List[str]] = Field(description="Specific questions to analyze (optional)")
    analysis_type: str = Field(description="Type of analysis to perform", default="comprehensive")

class SurveyAnalysisOutput(BaseModel):
    themes: List[str] = Field(description="Key themes identified")
    sentiment: str = Field(description="Overall sentiment analysis")
    insights: List[str] = Field(description="Actionable insights")
    recommendations: List[str] = Field(description="Specific recommendations")
    response_count: int = Field(description="Number of responses analyzed")

class SurveyAnalysisTool(MaxTool):
    name: str = "analyze_survey_responses"
    description: str = "Analyze survey responses to extract themes and actionable insights"
    thinking_message: str = "Analyzing your survey responses"
    args_schema: type[BaseModel] = SurveyAnalysisArgs
    
    async def _arun_impl(self, survey_id: str, question_ids: Optional[List[str]] = None, analysis_type: str = "comprehensive"):
        # Implementation here
```

**Data Extraction Logic**:
```python
# Extract all open-ended responses using processed data
all_open_responses = []

for question_id, processed_data in survey_responses.items():
    if processed_data.type == "open":
        # Pure open questions
        for response in processed_data.data:
            all_open_responses.append({
                'text': response.response,
                'question_id': question_id,
                'question_type': 'open',
                'person_data': response.person_properties,
                'timestamp': response.timestamp
            })
    
    elif processed_data.type in ["single_choice", "multiple_choice"]:
        # Custom responses from choice questions (isPredefined = false)
        custom_responses = [item for item in processed_data.data if not item.isPredefined]
        for response in custom_responses:
            all_open_responses.append({
                'text': response.label,  # The label IS the custom text
                'question_id': question_id,
                'question_type': f'{processed_data.type}_open',
                'person_data': response.person_properties,
                'timestamp': response.timestamp
            })
```

### Phase 2: Frontend Integration

**Files to Update**:

1. **`frontend/src/queries/schema/schema-assistant-messages.ts`**
   - Add `analyze_survey_responses` to `AssistantContextualTool` union
   - Run `pnpm schema:build` after changes

2. **`frontend/src/scenes/max/max-constants.tsx`**
   - Add tool definition:
   ```tsx
   analyze_survey_responses: {
       name: 'Analyze survey responses',
       description: 'Analyze survey responses to extract themes and actionable insights',
       product: Scene.Surveys,
   },
   ```

3. **Survey Results View Integration**
   - Mount MaxTool component in survey results interface
   - Likely locations: `SurveyView.tsx` or question visualization components
   - Pass survey ID and context data

### Phase 3: Evaluation Framework

**New File**: `ee/hogai/eval/eval_survey_analysis.py`

**Test Scenarios**:
- Pure open question analysis accuracy
- Single choice with open input extraction and analysis
- Multiple choice with open input extraction and analysis
- Mixed survey analysis (all question types combined)
- Theme identification quality
- Sentiment analysis accuracy
- Actionable insight generation
- Person context integration
- Performance with different response volumes

**Scoring Metrics**:
- Text extraction completeness
- Theme categorization accuracy
- Sentiment analysis correctness
- Insight actionability
- Source attribution accuracy

---

## Technical Implementation Details

### Data Access Pattern
1. Use existing `consolidatedSurveyResults` from surveyLogic
2. Access processed response data (avoid raw query parsing)
3. Leverage `isPredefined: false` flag for clean open-ended content extraction
4. Maintain person context and metadata throughout analysis

### Analysis Capabilities
- **Comprehensive Text Collection**: Extract from all open-ended sources
- **Theme Extraction**: Identify common themes across responses
- **Sentiment Analysis**: Analyze overall sentiment
- **Source Attribution**: Track insights by question type
- **Person Context Integration**: Use person properties for segmented insights
- **Actionable Recommendations**: Generate specific, actionable suggestions

---

## File Status Checklist

### Backend
- [ ] Extend `products/surveys/backend/max_tools.py` with SurveyAnalysisTool
- [ ] Implement data extraction logic using processed survey responses
- [ ] Add proper error handling and validation
- [ ] Test with real survey data

### Frontend
- [ ] Update `frontend/src/queries/schema/schema-assistant-messages.ts`
- [ ] Run `pnpm schema:build`
- [ ] Update `frontend/src/scenes/max/max-constants.tsx`
- [ ] Mount MaxTool in survey results view
- [ ] Test UI integration

### Evaluation
- [ ] Create `ee/hogai/eval/eval_survey_analysis.py`
- [ ] Implement comprehensive test scenarios
- [ ] Add scoring metrics and validation
- [ ] Run evaluations and validate quality

### Testing
- [ ] Backend unit tests for data extraction logic
- [ ] Integration tests with real survey data
- [ ] Frontend integration tests
- [ ] End-to-end workflow testing

---

## Key Technical Insights

### Leveraging Existing Infrastructure
- **Clean Data Extraction**: Use `isPredefined: false` to identify custom choice responses
- **Processed Data**: Leverage existing `processResultsForSurveyQuestions` output
- **Person Context**: Maintain user context throughout analysis
- **MaxTool Pattern**: Follow established MaxTool implementation patterns

### Success Metrics
- AI extracts ALL open-ended text from surveys (pure open + choice open inputs)
- Generated themes are relevant and comprehensive
- Insights are actionable and contextually appropriate
- Seamless integration with existing survey interface
- High-quality evaluation results

---

## Current Status: 🟡 BACKEND COMPLETE - NEED FRONTEND DATA FORMATTING

**Completed:**
- ✅ Comprehensive codebase analysis
- ✅ Data extraction strategy defined (IMPROVED: context-based approach)
- ✅ Backend `SurveyAnalysisTool` implemented (uses context data, no duplicate queries)
- ✅ Frontend schema updated (`analyze_survey_responses` added)
- ✅ Frontend constants updated (tool definition added)
- ✅ Implementation plan refined to use existing `consolidatedSurveyResults`

**Current Approach (IMPROVED):**
- **Frontend**: Format `consolidatedSurveyResults` data for LLM consumption
- **Frontend**: Extract open-ended responses using `isPredefined: false` pattern
- **Frontend**: Pass formatted data as MaxTool context
- **Backend**: Extract data from context (no duplicate queries)
- **Backend**: Focus purely on LLM analysis

**Next Steps:**
1. **START HERE**: Add data formatting logic to `surveyLogic.tsx`
2. Mount MaxTool in survey results interface with formatted context
3. Create evaluation framework
4. Test end-to-end functionality

**Context for Next Agent:**
- All analysis and planning is complete
- Data extraction strategy uses clean `isPredefined: false` pattern
- Implementation should follow existing MaxTool patterns in the same file
- Focus on comprehensive open-ended content analysis (pure open + choice custom inputs)
- Evaluation framework critical for production readiness