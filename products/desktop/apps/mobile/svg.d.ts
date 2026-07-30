// Lets us `import Logo from "./logo.svg"` and have it typed as a React
// component, courtesy of react-native-svg-transformer at build time.
declare module "*.svg" {
  import type React from "react";
  import type { SvgProps } from "react-native-svg";
  const content: React.FC<SvgProps>;
  export default content;
}
