import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
	plugins: [tsconfigPaths({ root: "." })],
	test: {
		globals: true,
		environment: "node",
		testTimeout: 10000,
		setupFiles: ["tests/setup.ts"],
		include: ["tests/**/*.test.ts"],
		exclude: ["node_modules/**", "dist/**", "tests/**/*.integration.test.ts"],
	},
});
