import type { AgentServerConfig } from "../../server/types";
import type { TestRepo } from "./api";

export type { AgentServerConfig };

// Test RSA public key (for testing only - matches TEST_PRIVATE_KEY in agent-server.test.ts)
export const TEST_PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6ofeEmDBbLxuAgqPQUho
7T69vzsc7jRq+NTuPgDJA0EXfaSjuPQ4UwOFc8Jzr6x/MuHiPTfDkJ3uwcKXaKLk
p+A6AwEv290lH4o/0aBVEsmYk0KFs9B+qNlbrn4s9B3/gc5WRFZ4UkNa7r6kn/uJ
fHFoHjF2hV4HQ+ZEPBo70ebqisbzthJ79YTCUSnjjhBoAnqf9HOkpDFE10ngvlY8
qVYPfvMj8bSKTkO1yr/u3vzwNIpanoUUIeH6PQQFo1Ftfh527bIyQI43754MyI6W
o7kFcjIuxu/b/Dr4o4SzCYyQYd03W1SH4vkZFY/x/eFFHylkXyQNHi8pAFb04hX9
JwIDAQAB
-----END PUBLIC KEY-----`;

export function createAgentServerConfig(
  repo: TestRepo,
  overrides: Partial<AgentServerConfig> = {},
): AgentServerConfig {
  return {
    port: 3001,
    repositoryPath: repo.path,
    apiUrl: "http://localhost:8000",
    apiKey: "test-api-key",
    projectId: 1,
    jwtPublicKey: TEST_PUBLIC_KEY,
    mode: "interactive",
    taskId: "test-task-id",
    runId: "test-run-id",
    ...overrides,
  };
}
