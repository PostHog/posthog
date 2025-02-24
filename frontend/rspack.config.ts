import { rspack } from '@rspack/core';
import ReactRefreshPlugin from '@rspack/plugin-react-refresh';
import { defineConfig } from "@rspack/cli";
import path from 'path';
const isDev = process.env.NODE_ENV === 'development';

export default defineConfig({
  entry: path.resolve(__dirname, 'src/index.tsx'),
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'index_bundle.js',
  },
  devServer: {
    port: 8080,
  },
  experiments: {
    css: true,
  },
  resolve: {
    extensions: ['.js', '.jsx', '.ts', '.tsx'],
    alias: {
      '~': path.resolve(__dirname, 'src'),
      lib: path.resolve(__dirname, 'src/lib'),
      scenes: path.resolve(__dirname, 'src/scenes'),
      '@posthog/lemon-ui': path.resolve(__dirname, '@posthog/lemon-ui/src'),
      '@posthog/lemon-ui/*': path.resolve(__dirname, '@posthog/lemon-ui/src/*'),
      '@posthog/ee/exports': [
        path.resolve(__dirname, '../ee/exports'),
        path.resolve(__dirname, '@posthog/ee/exports'),
      ],
      storybook: path.resolve(__dirname, '../common/storybook'),
      types: path.resolve(__dirname, '../src/types'),
      cypress: path.resolve(__dirname, '../cypress'),
      process: 'process/browser',
      products: path.resolve(__dirname, '../products'),
      public: path.resolve(__dirname, './public'),
    },
    fallback: { "crypto": "crypto-browserify", "stream": "stream-browserify" }
  },
  plugins: [
    new rspack.CopyRspackPlugin({
      // `./src/file.txt` -> `./dist/file.txt`
      patterns: [{
        from: path.resolve(__dirname, 'src/index.html'), 
        to: path.resolve(__dirname, 'dist/index.html') 
      }],
    }),
    // new HtmlWebpackPlugin({
    //   title: 'PostHog',
    //   template: path.resolve(__dirname, 'src/index.html'),
    //   templateParameters: {
    //     // Add any template parameters you need
    //   },
    //   inject: true,
    //   minify: {
    //     ignoreCustomFragments: [
    //       /{%[\s\S]*?%}/,
    //       /{{[\s\S]*?}}/
    //     ]
    //   }
    // }),
    isDev && new ReactRefreshPlugin(),
    isDev && new rspack.HotModuleReplacementPlugin(),
    new rspack.ProgressPlugin({}),
  ],
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: [/node_modules/],
        loader: 'builtin:swc-loader',
        options: {
          jsc: {
            parser: {
              syntax: 'typescript',
            },
          },
        },
        type: 'javascript/auto',
      },
      {
        test: /\.(jsx?|tsx?)$/,
        exclude: /[\\/]node_modules[\\/]/,
        use: [
          {
            loader: 'builtin:swc-loader',
            options: {
              sourceMap: true,
              jsc: {
                parser: {
                  syntax: 'typescript',
                  tsx: true,
                },
                transform: {
                  react: {
                    runtime: 'automatic',
                    development: isDev,
                    refresh: isDev,
                  },
                },
              },
              env: {
                targets: [
                  'chrome >= 87',
                  'edge >= 88',
                  'firefox >= 78',
                  'safari >= 14',
                ],
              },
            },
          },
        ],
        type: 'javascript/auto',
      },
      {
        test: /\.(sass|scss)$/,
        use: {
          loader: 'sass-loader',
          options: {
            api: 'modern-compiler',
            implementation: 'sass-embedded',
          },
        },
        type: 'css',
      },
      {
        test: /\.css$/,
        use: {
          loader: 'builtin:lightningcss-loader',
        },
        type: 'css',
      },
      {
        test: /\.(png|jpe?g|gif|svg|lottie)$/,
        type: 'asset/resource'
      },
    ],
  },

});