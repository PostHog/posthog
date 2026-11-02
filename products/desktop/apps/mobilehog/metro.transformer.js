const path = require("node:path");

const upstream = require(
  require.resolve("@expo/metro-config/babel-transformer", {
    paths: [path.dirname(require.resolve("expo/package.json"))],
  }),
);

// The WebView gets mermaid's browser bundle as text. Exporting it as a string
// keeps Hermes from running a DOM library and keeps it out of startup until a
// diagram requires it.
const RAW_MODULES = [path.join("mermaid", "dist", "mermaid.min.js")];

module.exports = {
  ...upstream,
  transform(props) {
    if (RAW_MODULES.some((suffix) => props.filename.endsWith(suffix))) {
      return upstream.transform({
        ...props,
        src: `module.exports = ${JSON.stringify(props.src)};`,
      });
    }
    return upstream.transform(props);
  },
};
