import sdkPackage from '@posthog/sdk/package.json'

import type { GeneratedFile } from './files'

const guide = `# PostHog definitions

The exports in index.ts tell PostHog which definitions this stack manages.

1. Change anything managed in code by editing its definition here. Never create a copy through the API or an MCP tool.
2. Add a new event, property, flag or metric in the same pull request as the code that uses it.
3. Run \`npm run typecheck\` in this folder, then \`npx hog check\`. Fix each problem before continuing. Commit package-lock.json whenever the dependencies change.
4. Run \`npx hog diff\` and include its output in the pull request. The pull request shows the diff, and a person runs \`hog push\` after the merge. Never run \`push\` yourself.
5. Review removals carefully. Removing a definition can remove the entity the stack created. An adopted entity stays in PostHog when you release it. Keep definitions that are still in use.
6. Keep secret values in PostHog. Refer to a secret by name with \`secret('NAME')\`.
7. Keep definitions pure. Do not read the network, clock or environment when building them.
`

export function scaffold(): GeneratedFile[] {
    const json = (value: unknown): string => JSON.stringify(value, null, 2) + '\n'
    return [
        {
            path: 'package.json',
            contents: json({
                private: true,
                type: 'module',
                scripts: { typecheck: 'tsc --noEmit' },
                dependencies: { '@posthog/sdk': sdkPackage.version },
                devDependencies: { typescript: '^5.9.3' },
            }),
        },
        {
            path: 'tsconfig.json',
            contents: json({
                compilerOptions: {
                    target: 'ES2022',
                    module: 'ESNext',
                    moduleResolution: 'Bundler',
                    strict: true,
                    noEmit: true,
                    skipLibCheck: true,
                },
                include: ['**/*.ts'],
            }),
        },
        { path: 'index.ts', contents: 'export {}\n' },
        { path: 'AGENTS.md', contents: guide },
    ]
}
