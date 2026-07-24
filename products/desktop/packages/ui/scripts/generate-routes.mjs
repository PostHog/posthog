import path from "node:path";
import { fileURLToPath } from "node:url";
import { Generator, getConfig } from "@tanstack/router-generator";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

const config = getConfig(
  {
    target: "react",
    autoCodeSplitting: true,
    routesDirectory: path.resolve(root, "src/router/routes"),
    generatedRouteTree: path.resolve(root, "src/router/routeTree.gen.ts"),
  },
  root,
);

const generator = new Generator({ config, root });
await generator.run();
console.log("Generated routeTree.gen.ts");
