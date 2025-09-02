/* global require, module, process, __dirname */
const path = require('path')

const HtmlWebpackPlugin = require('html-webpack-plugin')
const HtmlWebpackHarddiskPlugin = require('html-webpack-harddisk-plugin')

const webpackDevServerHost = process.env.WEBPACK_HOT_RELOAD_HOST || '127.0.0.1'
const webpackDevServerFrontendAddr = webpackDevServerHost === '0.0.0.0' ? '127.0.0.1' : webpackDevServerHost

function createEntry(entry) {
    const commonLoadersForSassAndLess = [
        {
            loader: 'style-loader',
        },
        {
            // This loader resolves url() and @imports inside CSS
            loader: 'css-loader',
        },
        {
            // Then we apply postCSS fixes like autoprefixer and minifying
            loader: 'postcss-loader',
        },
    ]

    return {
        name: entry,
        mode: process.env.NODE_ENV === 'production' ? 'production' : 'development',
        devtool:
            process.env.GENERATE_SOURCEMAP === 'false'
                ? false
                : process.env.NODE_ENV === 'production'
                  ? 'source-map'
                  : 'inline-source-map',
        entry: {
            [entry]: entry === 'main' ? './src/index.tsx' : null,
        },
        watchOptions: {
            ignored: /node_modules/,
        },
        output: {
            path: path.resolve(__dirname, 'dist'),
            chunkFilename: '[name].[contenthash].js',
            publicPath: process.env.JS_URL
                ? `${process.env.JS_URL}${process.env.JS_URL.endsWith('/') ? '' : '/'}static/`
                : process.env.NODE_ENV === 'production'
                  ? '/static/'
                  : `http${process.env.LOCAL_HTTPS ? 's' : ''}://${webpackDevServerFrontendAddr}:8234/static/`,
        },
        resolve: {
            extensions: ['.js', '.jsx', '.ts', '.tsx'],
            alias: {
                '~': path.resolve(__dirname, '..', '..', 'frontend', 'src'),
                lib: path.resolve(__dirname, '..', '..', 'frontend', 'src', 'lib'),
                scenes: path.resolve(__dirname, '..', '..', 'frontend', 'src', 'scenes'),
                '@posthog/lemon-ui': path.resolve(__dirname, '..', '..', 'frontend', '@posthog', 'lemon-ui', 'src'),
                '@posthog/ee/exports': [
                    path.resolve(__dirname, '..', '..', 'ee', 'frontend', 'exports'),
                    path.resolve(__dirname, '..', '..', 'frontend', '@posthog', 'ee', 'exports'),
                ],
                storybook: path.resolve(__dirname, '..', '..', 'frontend', '.storybook'),
                types: path.resolve(__dirname, '..', '..', 'frontend', 'types'),
                public: path.resolve(__dirname, '..', '..', 'frontend', 'public'),
                process: 'process/browser',
                products: path.resolve(__dirname, '..', '..', 'products'),
            },
            fallback: {
                crypto: require.resolve('crypto-browserify'),
                stream: require.resolve('stream-browserify'),
                buffer: require.resolve('buffer/'),
            },
        },
        module: {
            rules: [
                {
                    test: /\.[jt]sx?$/,
                    exclude: /(node_modules)/,
                    use: {
                        loader: 'babel-loader',
                    },
                },
                {
                    // Apply rule for .sass, .scss or .css files
                    test: /\.(sa|sc|c)ss$/,

                    // Set loaders to transform files.
                    // Loaders are applying from right to left(!)
                    // The first loader will be applied after others
                    use: [
                        ...commonLoadersForSassAndLess,
                        {
                            // First we transform SASS to standard CSS
                            loader: 'sass-loader',
                            options: {
                                implementation: require('sass'),
                            },
                        },
                    ].filter((a) => a),
                },
                {
                    // Apply rule for less files (used to import and override AntD)
                    test: /\.(less)$/,
                    use: [
                        ...commonLoadersForSassAndLess,
                        {
                            loader: 'less-loader', // compiles Less to CSS
                            options: {
                                lessOptions: {
                                    javascriptEnabled: true,
                                },
                            },
                        },
                    ],
                },

                {
                    // Now we apply rule for images
                    test: /\.(png|jpe?g|gif|svg|lottie)$/,
                    use: [
                        {
                            // Using file-loader for these files
                            loader: 'file-loader',

                            // In options we can set different things like format
                            // and directory to save
                            options: {
                                name: '[name].[contenthash].[ext]',
                                outputPath: 'images',
                            },
                        },
                    ],
                },
                {
                    // Apply rule for fonts files
                    test: /\.(woff|woff2|ttf|otf|eot)$/,
                    use: [
                        {
                            // Using file-loader too
                            loader: 'file-loader',
                            options: {
                                name: '[name].[contenthash].[ext]',
                                outputPath: 'fonts',
                            },
                        },
                    ],
                },
                {
                    // Apply rule for sound files
                    test: /\.(mp3)$/,
                    use: [
                        {
                            // Using file-loader too
                            loader: 'file-loader',
                            options: {
                                name: '[name].[contenthash].[ext]',
                                outputPath: 'sounds',
                            },
                        },
                    ],
                },
                // probably only need this because we're using webpack v4
                {
                    test: /monaco-editor\/.*\.m?js/,
                    loader: 'babel-loader',
                },
            ],
        },
        // add devServer config only to 'main' entry
        ...(entry === 'main'
            ? {
                  devServer: {
                      contentBase: path.join(__dirname, 'dist'),
                      hot: true,
                      host: webpackDevServerHost,
                      port: 8234,
                      stats: 'minimal',
                      disableHostCheck: !!process.env.LOCAL_HTTPS,
                      public: process.env.JS_URL
                          ? new URL(process.env.JS_URL).host
                          : `${webpackDevServerFrontendAddr}:8234`,
                      headers: {
                          'Access-Control-Allow-Origin': '*',
                          'Access-Control-Allow-Headers': '*',
                      },
                  },
              }
            : {}),
        plugins: [
            // common plugins for all entrypoints
        ].concat(
            entry === 'main'
                ? [
                      // we need these only once per build
                      new HtmlWebpackPlugin({
                          alwaysWriteToDisk: true,
                          title: 'PostHog',
                          template: path.join(__dirname, 'src', 'index.html'),
                      }),

                      new HtmlWebpackPlugin({
                          alwaysWriteToDisk: true,
                          title: 'PostHog',
                          filename: 'layout.html',
                          inject: false,
                          template: path.join(__dirname, 'src', 'layout.ejs'),
                      }),
                      new HtmlWebpackHarddiskPlugin(),
                  ]
                : []
        ),
    }
}

// main = app
module.exports = () => [createEntry('main')]
module.exports.createEntry = createEntry
