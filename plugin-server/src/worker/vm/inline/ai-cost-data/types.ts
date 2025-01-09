interface TextOperator {
    operator: "equals" | "startsWith" | "includes";
    value: string;
  }
  

export interface ModelRow {
    model: TextOperator;
    cost: {
      prompt_token: number;
      completion_token: number;
    };
    dateRange?: {
      start: string;
      end: string;
    };
  }