import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { trpcClient } from "../trpc";

registerRendererStateStorage({
  getItem: async (key: string): Promise<string | null> => {
    return await trpcClient.secureStore.getItem.query({ key });
  },
  setItem: async (key: string, value: string): Promise<void> => {
    await trpcClient.secureStore.setItem.query({ key, value });
  },
  removeItem: async (key: string): Promise<void> => {
    await trpcClient.secureStore.removeItem.query({ key });
  },
});
