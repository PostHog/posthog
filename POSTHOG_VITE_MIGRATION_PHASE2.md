# PostHog Vite Migration - Phase 2 Progress

## Overview

Phase 2 focused on enhancing the Vite configuration to match ESBuild functionality. Significant progress was made, with one remaining challenge related to pre-compiled dependencies.

## ✅ Completed in Phase 2

### 1. Multiple Entry Points Configuration

- ✅ Added all ESBuild entry points to Vite:
    - `index` (src/index.tsx) - Main PostHog App
    - `exporter` (src/exporter/index.tsx) - Exporter functionality
    - `render-query` (src/render-query/index.tsx) - Render Query functionality
    - `toolbar` (src/toolbar/index.tsx) - Toolbar
    - `testWorker` (src/scenes/session-recordings/player/testWorker.ts) - Test Worker

### 2. Output Structure and Naming

- ✅ Configured Vite output to match ESBuild naming conventions:
    - No hashes in dev mode: `[name].js`
    - Hashes in production: `[name]-[hash].js`
    - Chunk naming: `chunk-[name]-[hash].js`
    - Asset naming: `assets/[name]-[hash].[ext]`

### 3. Asset Copying Implementation

- ✅ Created `vite-asset-plugin.ts` to replicate ESBuild asset copying:
    - Copies public folder to dist
    - Copies snappy WASM file (`snappy_bg.wasm`)
    - Copies RRWeb worker map files
    - Logging for transparency

### 4. Environment Variables and Defines

- ✅ Configured environment variables to match ESBuild:
    - `process.env.NODE_ENV`
    - `global` → `globalThis`
    - `__DEV__` and `__PROD__` flags

### 5. Worker Build Configuration

- ✅ Enhanced worker configuration:
    - ES module format for WASM support
    - Proper chunk naming for workers
    - React plugin support for workers

### 6. Node.js Polyfills Setup

- ✅ Added polyfill aliases for browser compatibility:
    - `buffer` → `buffer`
    - `crypto` → `crypto-browserify`
    - `stream` → `stream-browserify`
    - `util` → `util`
    - `process` → `process/browser`

## ⚠️ Remaining Challenge: HogVM Module Buffer Import

### The Issue

The build fails due to a pre-compiled dependency in `/common/hogvm/typescript/dist/module.js`:

```javascript
import { Buffer as $62dAA$Buffer } from 'buffer'
```

This file is compiled by Parcel and imports `buffer` directly. Vite externalizes `buffer` for browser compatibility, causing the build to fail with:

```
"Buffer" is not exported by "__vite-browser-external"
```

### Attempted Solutions

1. ✅ Manual polyfill aliases
2. ✅ Custom external configuration
3. ✅ SSR noExternal configuration
4. ✅ Custom polyfill plugin

### Potential Solutions for Phase 3

1. **Rebuild HogVM TypeScript module** - Recompile without Buffer dependency
2. **Transform plugin** - Create Vite plugin to transform the Buffer import
3. **Alternative HogVM build** - Use source TypeScript instead of pre-compiled JS
4. **Buffer shim injection** - Inject Buffer polyfill before the problematic import

## Files Created/Modified

### New Files Created:

- `frontend/vite-asset-plugin.ts` - Asset copying functionality
- `frontend/vite-polyfill-plugin.ts` - Custom polyfill handling
- `frontend/vite-buffer-plugin.ts` - Buffer injection attempt

### Modified Files:

- `frontend/vite.config.ts` - Enhanced with all ESBuild functionality

## Testing Status

### ✅ Working:

- Flag-based build switching (`POSTHOG_USE_VITE_PROD=1`)
- Vite config loads without errors
- Asset copying plugins execute successfully
- Entry point configuration is correct
- Build process starts and transforms 7,655+ modules

### ❌ Failing:

- Final build due to Buffer polyfill issue in HogVM module

## Next Steps (Phase 3)

1. Resolve the HogVM Buffer import issue
2. Test complete build output compatibility
3. Compare bundle sizes with ESBuild
4. Add specialized plugins (toolbar deny-list)
5. Performance optimization and testing

## Usage

```bash
# Phase 2 enhanced Vite build (currently fails at final step)
POSTHOG_USE_VITE_PROD=1 pnpm build:vite

# Phase 1 ESBuild (still working)
pnpm build
```

## Summary

Phase 2 successfully implemented ~90% of ESBuild functionality in Vite. The configuration is comprehensive and handles most complex requirements. The remaining 10% is a specific polyfill issue with a pre-compiled dependency that requires targeted resolution.
