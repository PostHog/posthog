import { render } from "ink";
import { TuiAuth } from "./auth";
import { Root } from "./components/Root";
import { stopLocals } from "./local";
import { MouseInput } from "./mouse";
import { applyTheme, detectTheme } from "./theme";

applyTheme(await detectTheme());
const mouse = new MouseInput();
const root = (Component: typeof Root) => (
  <Component initialAuth={TuiAuth.load()} mouse={mouse.events} />
);
const instance = render(root(Root), {
  stdin: mouse.stdin,
  alternateScreen: true,
  exitOnCtrlC: false,
  // Forced on so Cmd and Ctrl+Shift arrive as modifiers where the terminal supports it; others ignore it.
  kittyKeyboard: { mode: "enabled" },
});
mouse.enable();

let reloading = false;
if (import.meta.hot) {
  // A swapped Root starts with fresh state, so it rereads the session a sign-in may have saved.
  import.meta.hot.accept("./components/Root", (next) => {
    if (next) instance.rerender(root(next.Root));
  });
  // Any other edit re-runs this module, so tear down this copy first. A full reload skips dispose, so it listens too.
  const teardown = (): void => {
    if (reloading) return;
    reloading = true;
    mouse.dispose();
    instance.unmount();
  };
  import.meta.hot.dispose(teardown);
  import.meta.hot.on("vite:beforeFullReload", teardown);
}

// Not awaited: a full reload waits for this module to finish, and Vite holds every later reload behind it.
void instance.waitUntilExit().then(async () => {
  if (reloading) return;
  mouse.dispose();
  await stopLocals();
  process.exit(0);
});
