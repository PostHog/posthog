import * as SecureStore from "expo-secure-store";
import type { StoredTokens } from "../types";

const TOKENS_KEY = "posthog_oauth_tokens";

export async function saveTokens(tokens: StoredTokens): Promise<void> {
  await SecureStore.setItemAsync(TOKENS_KEY, JSON.stringify(tokens));
}

export async function getTokens(): Promise<StoredTokens | null> {
  const value = await SecureStore.getItemAsync(TOKENS_KEY);
  if (!value) return null;

  try {
    return JSON.parse(value) as StoredTokens;
  } catch {
    return null;
  }
}

export async function deleteTokens(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKENS_KEY);
}
