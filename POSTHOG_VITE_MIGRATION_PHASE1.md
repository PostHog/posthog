# PostHog Vite Migration - Phase 1 Complete

## Overview

Phase 1 has implemented the basic infrastructure for flag-based builds between ESBuild and Vite for production.

## Changes Made

### 1. Environment Variable Support

- Added `POSTHOG_USE_VITE_PROD` environment variable
- When set to `"1"`, uses Vite for production builds
- Defaults to ESBuild when not set or set to other values

### 2. Package.json Scripts

- Modified `build` script to conditionally use Vite or ESBuild
- Added `build:vite` script that runs `pnpm build:products && vite build`
- Existing `build:esbuild` script remains unchanged

### 3. Build Logic

- Modified `frontend/build.mjs` to skip ESBuild process when `POSTHOG_USE_VITE_PROD=1`
- Graceful exit with informative message when Vite is used

## Usage

### Development (unchanged)

```bash
pnpm start  # Uses ESBuild dev server
pnpm start-vite  # Uses Vite dev server
```

### Production Builds

#### ESBuild (current default)

```bash
pnpm build
# or explicitly
POSTHOG_USE_VITE_PROD=0 pnpm build
```

#### Vite (new system)

```bash
POSTHOG_USE_VITE_PROD=1 pnpm build
```

## CI/CD Integration Points

### Docker Builds

For production Docker builds, the environment variable should be set in the Dockerfile at line 46:

```dockerfile
RUN POSTHOG_USE_VITE_PROD=1 bin/turbo --filter=@posthog/frontend build
```

### GitHub Actions

The frontend CI workflow (`ci-frontend.yml`) should be updated to test both build systems:

- Line 142: Build script for toolbar bundle size check
- Line 46: Frontend build command in turbo filter

### Deployment Options

1. **Feature Flag Testing**: Set environment variable in specific deployments for testing
2. **Gradual Rollout**: Use different build systems in different environments
3. **A/B Testing**: Compare build artifacts between systems

## Next Steps (Phase 2)

1. Enhance Vite config to match all ESBuild functionality
2. Implement proper entry points and output structure
3. Add asset copying (WASM, RRWeb workers, public files)
4. Test bundle compatibility with existing infrastructure

## Testing the Flag

```bash
# Test ESBuild (should work as before)
pnpm build

# Test Vite (should use Vite build process)
POSTHOG_USE_VITE_PROD=1 pnpm build

# Check that the flag properly skips ESBuild
POSTHOG_USE_VITE_PROD=1 node frontend/build.mjs
```

## Notes

- This is backward compatible - existing builds continue to work unchanged
- The Vite build currently produces different output structure than ESBuild
- Phase 2 will focus on making Vite output match ESBuild exactly
- No breaking changes introduced in this phase
