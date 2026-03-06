import './theme.css'

import type { StoryFn } from '@storybook/react'
import type { ReactElement } from 'react'

/**
 * MCP Apps host CSS variables — simulates what the host injects via useHostStyleVariables.
 * See: https://github.com/modelcontextprotocol/ext-apps/blob/main/src/spec.types.ts
 */
const mcpAppsCssVariables: Record<string, string> = {
    // Background
    '--color-background-primary': '#ffffff',
    '--color-background-secondary': '#f9fafb',
    '--color-background-tertiary': '#f2f4f7',
    '--color-background-inverse': '#101828',
    '--color-background-ghost': 'transparent',
    '--color-background-info': '#eff6ff',
    '--color-background-danger': '#fef2f2',
    '--color-background-success': '#f0fdf4',
    '--color-background-warning': '#fffbeb',
    '--color-background-disabled': '#f2f4f7',
    // Text
    '--color-text-primary': '#101828',
    '--color-text-secondary': '#6b7280',
    '--color-text-tertiary': '#9ca3af',
    '--color-text-inverse': '#ffffff',
    '--color-text-ghost': '#6b7280',
    '--color-text-info': '#2563eb',
    '--color-text-danger': '#dc2626',
    '--color-text-success': '#059669',
    '--color-text-warning': '#d97706',
    '--color-text-disabled': '#9ca3af',
    // Border
    '--color-border-primary': '#e5e7eb',
    '--color-border-secondary': '#d1d5db',
    '--color-border-tertiary': '#f2f4f7',
    '--color-border-inverse': '#374151',
    '--color-border-ghost': 'transparent',
    '--color-border-info': '#bfdbfe',
    '--color-border-danger': '#fecaca',
    '--color-border-success': '#bbf7d0',
    '--color-border-warning': '#fde68a',
    '--color-border-disabled': '#e5e7eb',
    // Fonts
    '--font-sans': "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    '--font-mono': "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
    '--font-weight-normal': '400',
    '--font-weight-medium': '500',
    '--font-weight-semibold': '600',
    '--font-weight-bold': '700',
    // Border radius
    '--border-radius-xs': '0.125rem',
    '--border-radius-sm': '0.25rem',
    '--border-radius-md': '0.375rem',
    '--border-radius-lg': '0.5rem',
    '--border-radius-xl': '0.75rem',
    '--border-radius-full': '9999px',
}

/** Decorator that injects MCP Apps host CSS variables onto the story root. */
export function McpThemeDecorator(Story: StoryFn): ReactElement {
    return (
        <div
            style={
                {
                    ...mcpAppsCssVariables,
                    fontFamily: 'var(--font-sans)',
                    color: 'var(--color-text-primary)',
                    backgroundColor: 'var(--color-background-primary)',
                    padding: '1.5rem',
                    maxWidth: 720,
                    minHeight: 200,
                } as React.CSSProperties
            }
        >
            <Story />
        </div>
    )
}
