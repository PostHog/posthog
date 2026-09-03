// react-native-web ships no type declarations. Tests use it as the DOM stand-in
// for react-native, so borrow that module's surface rather than widen to any.
declare module "react-native-web" {
  export * from "react-native";
}
