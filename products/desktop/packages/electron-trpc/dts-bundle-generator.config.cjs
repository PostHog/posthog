const config = {
  compilationOptions: {
    preferredConfigPath: "./tsconfig.json",
  },
  entries: [
    {
      filePath: "./src/renderer/index.ts",
      outFile: `./dist/renderer.d.ts`,
      noCheck: true,
    },
    {
      filePath: "./src/main/index.ts",
      outFile: `./dist/main.d.ts`,
      noCheck: true,
    },
  ],
};

module.exports = config;
