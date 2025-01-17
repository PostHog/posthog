{
    "name": "@posthog/apps-common",
        "version": "0.0.0",
            "license": "MIT",
                "source": "src/index.ts",
                    "main": "dist/index.js",
                        "types": "dist/index.d.ts",
                            "scripts": {
        "build": "pnpm build:source && pnpm build:types && ls -lah dist/",
            "build:source": "echo \"Building source\" && node build.mjs",
                "build:types": "echo \"Building types\" && tsup src/index.ts --dts-only",
                    "prepublishOnly": "pnpm build"
    },
    "devDependencies": {
        "tsup": "^5.12.8",
            "typescript": ">=4.0.0"
    },
    "peerDependencies": {
        "@posthog/lemon-ui": "*",
            "kea": "*",
                "kea-router": "*",
                    "react": "*",
                        "react-dom": "*"
    }
}