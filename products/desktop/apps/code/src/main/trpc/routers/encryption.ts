import { container } from "@main/di/container";
import { ENCRYPTION_SERVICE } from "@main/di/tokens";
import type { EncryptionService } from "@main/services/encryption/service";
import { z } from "zod";
import { publicProcedure, router } from "../trpc";

const getService = () => container.get<EncryptionService>(ENCRYPTION_SERVICE);

export const encryptionRouter = router({
  encrypt: publicProcedure
    .input(z.object({ stringToEncrypt: z.string() }))
    .query(({ input }) => getService().encrypt(input.stringToEncrypt)),

  decrypt: publicProcedure
    .input(z.object({ stringToDecrypt: z.string() }))
    .query(({ input }) => getService().decrypt(input.stringToDecrypt)),
});
