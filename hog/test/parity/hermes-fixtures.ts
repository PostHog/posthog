// Hand-written React Native files. The packager map has odd numbers and escapes to check key order
// and number output, and the composed map has a stale release that event-mode `clone` must clear.

const PACKAGER_MAP =
    '{\n  "version": 3,\n  "sources": ["src/App.js", "node_modules/react-native/Libraries/polyfill.js"],\n  "sourcesContent": ["function App() {\\n  return \\"h\u00e9llo\\";\\n}\\nApp();\\n", null],\n  "x_facebook_sources": [[{"names": ["<global>", "App"], "mappings": "AAA,CCC"}], null],\n  "names": ["App"],\n  "mappings": "AACA;AAAA,SAAUA",\n  "x_google_ignoreList": [1],\n  "x_test": {"b": 1.0, "a": "\u2028/\u00e9\\u0001\\u007f", "z": 1e21, "n": -0, "big": 18446744073709551616}\n}\n'

const BUNDLE =
    'var __BUNDLE_START_TIME__=this.nativePerformanceNow?nativePerformanceNow():Date.now();\nfunction App(){return "h\u00e9llo"}App();\n//# sourceMappingURL=index.android.bundle.map'

export const COMPOSED_MAP =
    '{"version":3,"sources":["src/App.js","node_modules/react-native/Libraries/polyfill.js"],"sourcesContent":["function App() {\\n  return \\"h\u00e9llo\\";\\n}\\nApp();\\n",null],"names":["App","<global>"],"mappings":"AAAA,SACA,cAAAC","x_facebook_sources":[[{"names":["<global>","App"],"mappings":"AAA,CCC"}],null],"x_hermes_function_offsets":{"0":[0,28],"1":[0]},"x_google_ignoreList":[1],"release_id":"11111111-2222-4333-8444-555555555555","x_unicode":"\ud83d\ude00 </script> \\"q\\" \\\\ \\t"}\n'

export const HERMES_BUNDLES: Record<string, string> = {
    'android/index.android.bundle': BUNDLE,
    'android/index.android.bundle.map': PACKAGER_MAP,
    'ios/main.jsbundle':
        'var __BUNDLE_START_TIME__=this.nativePerformanceNow?nativePerformanceNow():Date.now();\nfunction App(){return "h\u00e9llo"}App();\n//# sourceMappingURL=main.jsbundle.map\n//# debugId=C96BFA94CA844F988D5EF15ADBA692CA',
    'ios/main.jsbundle.map':
        '{"version": 3, "sources": ["src/App.js", "node_modules/react-native/Libraries/polyfill.js"], "sourcesContent": ["function App() {\\n  return \\"h\\u00e9llo\\";\\n}\\nApp();\\n", null], "x_facebook_sources": [[{"names": ["<global>", "App"], "mappings": "AAA,CCC"}], null], "names": ["App"], "mappings": "AACA;AAAA,SAAUA", "x_google_ignoreList": [1], "debugId": "c96bfa94-ca84-4f98-8d5e-f15adba692ca"}',
    'short/x.bundle': 'a\n',
    'short/x.bundle.map': '{"version":3,"sources":["s.js"],"names":[],"mappings":"AAAA;AACA;AACA"}',
}

export const HERMES_BUILD: Record<string, string> = {
    'android/index.android.bundle': BUNDLE,
    'android/index.android.bundle.map': PACKAGER_MAP,
    'android/hbc/index.android.bundle.hbc.composed.map': COMPOSED_MAP,
}

// Expo stamps a debugId on the packager map instead of running inject.
export const EXPO_BUILD: Record<string, string> = {
    'ios/main.jsbundle.map':
        '{"version": 3, "sources": ["src/App.js", "node_modules/react-native/Libraries/polyfill.js"], "sourcesContent": ["function App() {\\n  return \\"h\\u00e9llo\\";\\n}\\nApp();\\n", null], "x_facebook_sources": [[{"names": ["<global>", "App"], "mappings": "AAA,CCC"}], null], "names": ["App"], "mappings": "AACA;AAAA,SAAUA", "x_google_ignoreList": [1], "debugId": "c96bfa94-ca84-4f98-8d5e-f15adba692ca"}',
    'ios/hbc/main.jsbundle.hbc.composed.map': COMPOSED_MAP,
}
