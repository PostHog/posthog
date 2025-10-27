import { Plugin } from 'vite'

/**
 * Vite plugin to transform the HogVM module Buffer import
 * This plugin specifically handles the pre-compiled HogVM module that imports Buffer
 * and replaces Buffer usage with browser-compatible alternatives for base64 operations
 */
export function hogvmTransformPlugin(): Plugin {
    return {
        name: 'posthog-hogvm-transform',
        transform(code, id) {
            // Only transform the specific HogVM module file
            if (!id.includes('common/hogvm/typescript/dist/module.js')) {
                return null
            }

            // Replace the Buffer import with a browser-compatible implementation
            let transformedCode = code

            // 1. Remove the Buffer import
            transformedCode = transformedCode.replace(
                /import\s*{\s*Buffer\s+as\s+\$62dAA\$Buffer\s*}\s*from\s*["']buffer["'];?\s*/,
                '// Buffer import removed - using browser-compatible implementation\n'
            )

            // 2. Replace the Buffer assignment with a browser-compatible implementation
            transformedCode = transformedCode.replace(
                /var\s+\$23fc6ca6b1cb5ed8\$require\$Buffer\s*=\s*\$62dAA\$Buffer;/,
                `// Browser-compatible Buffer implementation for base64 operations
var $23fc6ca6b1cb5ed8$require$Buffer = {
    from: function(data, encoding) {
        if (encoding === 'base64') {
            // Decode base64 to string
            try {
                return {
                    toString: function() {
                        return atob(data);
                    }
                };
            } catch (e) {
                return {
                    toString: function() {
                        return '';
                    }
                };
            }
        } else {
            // Encode string data
            return {
                toString: function(outputEncoding) {
                    if (outputEncoding === 'base64') {
                        try {
                            return btoa(data);
                        } catch (e) {
                            return '';
                        }
                    }
                    return data;
                }
            };
        }
    }
};`
            )

            return {
                code: transformedCode,
                map: null, // We don't need source maps for this transformation
            }
        },
    }
}
