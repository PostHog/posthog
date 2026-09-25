const withPostHog = require("posthog-react-native/expo");

module.exports = function withPostHogSourceMaps(config) {
  // Builds without upload credentials must not require the release CLI.
  return process.env.POSTHOG_CLI_TOKEN ? withPostHog(config) : config;
};
