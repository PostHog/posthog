interface TextOperator {
    operator: "equals" | "startsWith" | "includes";
    value: string;
  }
  
  export interface ModelDetails {
    matches: string[];
    searchTerms: string[];
    info: {
      releaseDate: string;
      maxTokens?: number;
      description: string;
      tradeOffs: string[];
      benchmarks: {
        [key: string]: number;
      };
      capabilities: string[];
      strengths: string[];
      weaknesses: string[];
      recommendations: string[];
    };
  }
  
  export type ModelDetailsMap = {
    [key: string]: ModelDetails;
  };
  
  export interface ModelRow {
    model: TextOperator;
    cost: {
      prompt_token: number;
      completion_token: number;
    };
    showInPlayground?: boolean;
    targetUrl?: string;
    dateRange?: {
      start: string;
      end: string;
    };
  }
  
  export interface ModelRow {
    model: TextOperator;
    cost: {
      prompt_token: number;
      completion_token: number;
    };
    showInPlayground?: boolean;
    targetUrl?: string;
    dateRange?: {
      start: string;
      end: string;
    };
  }