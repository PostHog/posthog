/**
 *
 * DO NOT EDIT THIS FILE UNLESS IT IS IN /costs
 */

import { ModelRow } from "../../interfaces/Cost";

export const costs: ModelRow[] = [
  {
    model: {
      operator: "equals",
      value: "open-mistral-7b",
    },
    cost: {
      prompt_token: 0.00000025,
      completion_token: 0.00000025,
    },
  },
  {
    model: {
      operator: "equals",
      value: "open-mixtral-8x7b",
    },
    cost: {
      prompt_token: 0.0000007,
      completion_token: 0.0000007,
    },
  },
  {
    model: {
      operator: "equals",
      value: "mistral-small-latest",
    },
    cost: {
      prompt_token: 0.000002,
      completion_token: 0.000006,
    },
  },
  {
    model: {
      operator: "equals",
      value: "mistral-medium-latest",
    },
    cost: {
      prompt_token: 0.0000027,
      completion_token: 0.0000081,
    },
  },
  {
    model: {
      operator: "equals",
      value: "mistral-large-latest",
    },
    cost: {
      prompt_token: 0.000008,
      completion_token: 0.000024,
    },
  },
  {
    model: {
      operator: "equals",
      value: "mistral-embed",
    },
    cost: {
      prompt_token: 0.0000001,
      completion_token: 0.0000001,
    },
  },
];
