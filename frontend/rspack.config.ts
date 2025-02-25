import { rspack } from '@rspack/core';
import ReactRefreshPlugin from '@rspack/plugin-react-refresh';
import { defineConfig } from "@rspack/cli";
import path from 'path';
import HtmlWebpackPlugin from 'html-webpack-plugin';
const isDev = process.env.NODE_ENV === 'development';

const distPath = path.resolve(__dirname, 'dist');
export default defineConfig({
  mode: isDev ? 'development' : 'production',
  entry: {
    app: path.resolve(__dirname, './src/index.tsx'),
  },
  output: {
    globalObject: 'self',
    path: distPath,
    filename: '[name].js',
    publicPath: '/static/',
  },
  devServer: {
    port: 8010,
    host: process.env.WEBPACK_HOT_RELOAD_HOST || 'localhost',
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': '*',
    },
    devMiddleware: {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': '*',
      },
      publicPath: '/static/'
    },
    static: {
      directory: path.join(__dirname, 'dist'),
      publicPath: '/',
      serveIndex: true,
    },
    historyApiFallback: {
      index: '/index.html'
    }
  },
  experiments: {
    css: true,
    asyncWebAssembly: true,
  },
  resolve: {
    tsConfig: path.resolve(__dirname, 'tsconfig.dev.json'),
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
      // process: 'process/browser',
      products: path.resolve(__dirname, '../products'),
      public: path.resolve(__dirname, './public'),
      'process/browser': require.resolve('process/browser.js'),
    },
    fallback: {
      crypto: "crypto-browserify",
      stream: "stream-browserify",
      process: require.resolve('process/browser.js'),
    },
  },
  plugins: [
    new rspack.CopyRspackPlugin({
      // `./src/file.txt` -> `./dist/file.txt`
      patterns: [{
        from: path.resolve(__dirname, 'public'), 
        to: distPath 
      }],
    }),
    // new HtmlWebpackPlugin({
    //   title: 'PostHog',
    //   template: path.resolve(__dirname, 'src/index.ejs'),
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
    new HtmlWebpackPlugin({
      filename: path.join(distPath, 'index.html'), // explicitly set output path
      template: path.resolve(__dirname, 'src/index.html'),
      inject: true,
      templateParameters: false,
      minify: {
        removeComments: false,
        collapseWhitespace: false,
        ignoreCustomFragments: [
          /\{%[\s\S]*?%}/,
          /\{\{[\s\S]*?}}/
        ]
      }
    }),
    new rspack.ProvidePlugin({
      process: 'process/browser.js',
    }),
    // new HtmlRspackPlugin({
    //   title: 'PostHog',
    //   template: path.resolve(__dirname, 'src/index.ejs'),
    //   templateParameters: {
    //     // Add any template parameters you need
    //   },
    //   inject: true,
    //   // minify: {
    //   //   ignoreCustomFragments: [
    //   //     /{%[\s\S]*?%}/,
    //   //     /{{[\s\S]*?}}/
    //   //   ]
    //   // }
    // }),
    new rspack.DefinePlugin({
      'process.env.JS_URL': JSON.stringify(process.env.JS_URL),
      'process.env.LOCAL_HTTPS': JSON.stringify(process.env.LOCAL_HTTPS),
      'process.env.WEBPACK_HOT_RELOAD_HOST': JSON.stringify(process.env.WEBPACK_HOT_RELOAD_HOST),
      'process.env.WEBPACK_HOT_RELOAD_FRONTEND_ADDR': JSON.stringify(process.env.WEBPACK_HOT_RELOAD_FRONTEND_ADDR),
    }),
    isDev && new ReactRefreshPlugin({
      exclude: [/node_modules/, /\.json$/],  // Add JSON files to exclude
      include: /\.([jt]sx?|mjs)$/,  // Only include JS/TS files
      overlay: true
    }),
    isDev && new rspack.HotModuleReplacementPlugin(),
    new rspack.ProgressPlugin({}),
  ].filter(Boolean),
  module: {
    rules: [
      // Add specific JSON handling
      {
        test: /\.json$/,
        type: 'json',  // Use built-in JSON loader
        exclude: /node_modules/
      },
      {
        test: /\.tsx$/,
        use: {
          loader: 'builtin:swc-loader',
          options: {
            sourceMap: true,
            jsc: {
              parser: {
                syntax: 'typescript',
                jsx: true,
              },
              preserveAllComments: false,
              transform: {
                react: {
                  runtime: 'automatic',
                  throwIfNamespace: true,
                  useBuiltins: false,
                },
              },
            },
          },
        },
        type: 'javascript/auto',
      },
      {
        test: /\.ts$/,
        use: {
          loader: 'builtin:swc-loader',
          options: {
            sourceMap: true,
            jsc: {
              parser: {
                syntax: 'typescript',
              },
              preserveAllComments: false,
            },
          },
        },
        type: 'javascript/auto',
      },
      {
        test: /\.(sass|scss)$/,
        exclude: /node_modules/,
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
        exclude: /node_modules/,
        use: {
          loader: 'builtin:lightningcss-loader',
        },
        type: 'css',
      },
      {
        test: /\.(png|jpe?g|gif|svg|lottie)$/,
        exclude: /node_modules/,
        type: 'asset/resource'
      },
    ],
  },
});