export interface PromptHistoryOpenedProperties {
  entry_count: number;
}

export interface PromptHistorySelectedProperties {
  entry_count: number;
  entry_age_seconds: number | null;
  had_pending_draft: boolean;
  had_search_query: boolean;
  prompt_length: number;
}
