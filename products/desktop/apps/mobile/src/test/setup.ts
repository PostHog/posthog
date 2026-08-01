import { afterEach, vi } from "vitest";

vi.mock("expo-constants", () => ({
  default: {
    expoConfig: {
      version: "0.0.0-test",
    },
  },
}));

vi.mock("@react-native-async-storage/async-storage", () => {
  const store = new Map<string, string>();
  return {
    default: {
      getItem: vi.fn(async (key: string) => store.get(key) ?? null),
      setItem: vi.fn(async (key: string, value: string) => {
        store.set(key, value);
      }),
      removeItem: vi.fn(async (key: string) => {
        store.delete(key);
      }),
      clear: vi.fn(async () => {
        store.clear();
      }),
      getAllKeys: vi.fn(async () => Array.from(store.keys())),
      multiGet: vi.fn(async (keys: string[]) =>
        keys.map((key) => [key, store.get(key) ?? null]),
      ),
      multiSet: vi.fn(async (pairs: [string, string][]) => {
        for (const [key, value] of pairs) {
          store.set(key, value);
        }
      }),
      multiRemove: vi.fn(async (keys: string[]) => {
        for (const key of keys) {
          store.delete(key);
        }
      }),
    },
  };
});

vi.mock("phosphor-react-native", async () => {
  const { createElement } = await import("react");
  const icon = (name: string) => (props: Record<string, unknown>) =>
    createElement(name, props);
  return {
    __esModule: true,
    Archive: icon("Archive"),
    ArrowCounterClockwise: icon("ArrowCounterClockwise"),
    ArrowDown: icon("ArrowDown"),
    ArrowSquareOut: icon("ArrowSquareOut"),
    ArrowUp: icon("ArrowUp"),
    ArrowsClockwise: icon("ArrowsClockwise"),
    ArrowsIn: icon("ArrowsIn"),
    ArrowsOut: icon("ArrowsOut"),
    Brain: icon("Brain"),
    BrainIcon: icon("BrainIcon"),
    Bug: icon("Bug"),
    Camera: icon("Camera"),
    Cards: icon("Cards"),
    CaretDown: icon("CaretDown"),
    CaretLeft: icon("CaretLeft"),
    CaretRight: icon("CaretRight"),
    CaretUp: icon("CaretUp"),
    ChatCircle: icon("ChatCircle"),
    Check: icon("Check"),
    CheckCircle: icon("CheckCircle"),
    CircleDashed: icon("CircleDashed"),
    CircleIcon: icon("CircleIcon"),
    CircleNotch: icon("CircleNotch"),
    Clock: icon("Clock"),
    CloudArrowDown: icon("CloudArrowDown"),
    Code: icon("Code"),
    Copy: icon("Copy"),
    Eye: icon("Eye"),
    File: icon("File"),
    FileText: icon("FileText"),
    FunnelSimple: icon("FunnelSimple"),
    GearSix: icon("GearSix"),
    GitBranch: icon("GitBranch"),
    GitMerge: icon("GitMerge"),
    GitPullRequest: icon("GitPullRequest"),
    GithubLogo: icon("GithubLogo"),
    Globe: icon("Globe"),
    Image: icon("Image"),
    ImageBroken: icon("ImageBroken"),
    Lightning: icon("Lightning"),
    LinkSimple: icon("LinkSimple"),
    List: icon("List"),
    ListBullets: icon("ListBullets"),
    ListChecks: icon("ListChecks"),
    Lock: icon("Lock"),
    MagnifyingGlass: icon("MagnifyingGlass"),
    Microphone: icon("Microphone"),
    MicrophoneIcon: icon("MicrophoneIcon"),
    PaperclipIcon: icon("PaperclipIcon"),
    PauseIcon: icon("PauseIcon"),
    PencilIcon: icon("PencilIcon"),
    PencilSimple: icon("PencilSimple"),
    Play: icon("Play"),
    Plus: icon("Plus"),
    PuzzlePiece: icon("PuzzlePiece"),
    Question: icon("Question"),
    RadioButton: icon("RadioButton"),
    Robot: icon("Robot"),
    ShieldCheck: icon("ShieldCheck"),
    Sparkle: icon("Sparkle"),
    SpeakerHigh: icon("SpeakerHigh"),
    Stack: icon("Stack"),
    Stop: icon("Stop"),
    StopIcon: icon("StopIcon"),
    Terminal: icon("Terminal"),
    ThumbsDown: icon("ThumbsDown"),
    Trash: icon("Trash"),
    Tray: icon("Tray"),
    UsersThree: icon("UsersThree"),
    Warning: icon("Warning"),
    WarningCircle: icon("WarningCircle"),
    WifiSlash: icon("WifiSlash"),
    Wrench: icon("Wrench"),
    X: icon("X"),
    XCircle: icon("XCircle"),
  };
});

// nativewind cannot be evaluated under vitest's node environment — it pulls in
// react-native internals shipped as Flow source, which fail to parse ("Unexpected
// token 'typeof'") and wedge the module loader. Stub the two APIs the app uses so
// any module that imports the theme (directly or transitively) loads cleanly.
vi.mock("nativewind", () => ({
  useColorScheme: () => ({
    colorScheme: "light" as const,
    setColorScheme: vi.fn(),
    toggleColorScheme: vi.fn(),
  }),
  vars: (value: Record<string, string>) => value,
}));

// react-native-reanimated pulls in native worklet/runtime setup that never
// resolves under vitest's node environment, hanging the worker indefinitely.
// Replace it with a lightweight, side-effect-free stand-in so component trees
// that import it (directly or transitively) can render in tests.
vi.mock("react-native-reanimated", async () => {
  const { createElement } = await import("react");
  const animatedComponent =
    (name: string) => (props: Record<string, unknown>) =>
      createElement(name, props, (props?.children as never) ?? null);
  const passthroughEasing = () => 0;
  const easingFactory = () => passthroughEasing;

  return {
    default: {
      View: animatedComponent("Animated.View"),
      ScrollView: animatedComponent("Animated.ScrollView"),
      Text: animatedComponent("Animated.Text"),
      Image: animatedComponent("Animated.Image"),
      createAnimatedComponent: (component: unknown) => component,
    },
    Easing: {
      linear: passthroughEasing,
      ease: passthroughEasing,
      quad: passthroughEasing,
      cubic: passthroughEasing,
      in: easingFactory,
      out: easingFactory,
      inOut: easingFactory,
      bezier: easingFactory,
    },
    useSharedValue: <T>(initial: T) => ({ value: initial }),
    useAnimatedStyle: (factory: () => unknown) => {
      try {
        return factory();
      } catch {
        return {};
      }
    },
    useDerivedValue: (factory: () => unknown) => ({ value: factory() }),
    useAnimatedRef: () => ({ current: null }),
    withTiming: <T>(value: T) => value,
    withSpring: <T>(value: T) => value,
    withDelay: <T>(_delay: number, value: T) => value,
    withRepeat: <T>(value: T) => value,
    withSequence: <T>(...values: T[]) => values[values.length - 1],
    cancelAnimation: vi.fn(),
    runOnJS:
      <Args extends unknown[]>(fn: (...args: Args) => unknown) =>
      (...args: Args) =>
        fn(...args),
    runOnUI:
      <Args extends unknown[]>(fn: (...args: Args) => unknown) =>
      (...args: Args) =>
        fn(...args),
    interpolate: () => 0,
    Extrapolation: { CLAMP: "clamp", EXTEND: "extend", IDENTITY: "identity" },
  };
});

vi.mock("react-native-safe-area-context", async () => {
  const { createElement } = await import("react");
  return {
    SafeAreaProvider: (props: { children?: unknown }) =>
      createElement("SafeAreaProvider", null, props.children as never),
    SafeAreaView: (props: { children?: unknown }) =>
      createElement("SafeAreaView", null, props.children as never),
    useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
    useSafeAreaFrame: () => ({ x: 0, y: 0, width: 375, height: 812 }),
  };
});

vi.mock("react-native", async () => {
  const actual = await import("react-native-web");
  const { createElement } = await import("react");

  return {
    ...actual,
    Alert: {
      alert: vi.fn(),
    },
    BackHandler: {
      addEventListener: vi.fn(() => ({
        remove: vi.fn(),
      })),
    },
    InteractionManager: {
      runAfterInteractions: (callback: () => void) => {
        callback();
        return {
          cancel: vi.fn(),
        };
      },
    },
    Platform: {
      OS: "ios",
      select: <T>(options: { ios?: T; android?: T; default?: T }) =>
        options.ios ?? options.default,
    },
    TextInput: (props: Record<string, unknown>) =>
      createElement("TextInput", props),
  };
});

vi.mock("@/lib/logger", () => {
  const mockLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
    scope: () => mockLogger,
  };

  return {
    logger: mockLogger,
  };
});

afterEach(() => {
  vi.clearAllMocks();
});
