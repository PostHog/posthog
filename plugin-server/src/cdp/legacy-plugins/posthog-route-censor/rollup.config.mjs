import typescript from '@rollup/plugin-typescript';
import nodeResolve from '@rollup/plugin-node-resolve';

export default [
  {
    input: 'src/index.ts',
    output: [
      {
        name: 'main',
        format: 'cjs',
        file: 'dist/index.js'
      },
    ],
    plugins: [
      // Compile TypeScript files
      typescript({ tsconfig: './tsconfig.json' }),
      nodeResolve(),
    ],
  },
];
