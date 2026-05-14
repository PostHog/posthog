<script setup lang="ts">
withDefaults(
    defineProps<{
        title?: string
        size?: 'normal' | 'compact' | 'tight'
    }>(),
    { size: 'normal' }
)
</script>

<template>
    <div class="terminal" :class="[`size-${size}`]">
        <div class="terminal-titlebar">
            <span class="dot dot-red" />
            <span class="dot dot-yellow" />
            <span class="dot dot-green" />
            <span class="terminal-title">{{ title ?? 'zsh — ph' }}</span>
        </div>
        <div class="terminal-body">
            <slot />
        </div>
    </div>
</template>

<style scoped>
.terminal {
    border-radius: 10px;
    overflow: hidden;
    background: #1e1f29;
    box-shadow:
        0 10px 30px rgba(0, 0, 0, 0.25),
        0 0 0 1px rgba(255, 255, 255, 0.04);
    font-family: 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    margin: 0.5rem 0;
}

.terminal-titlebar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    background: linear-gradient(#3a3b48, #2c2d38);
    border-bottom: 1px solid rgba(0, 0, 0, 0.35);
    position: relative;
}

.dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    display: inline-block;
}

.dot-red {
    background: #ff5f56;
    box-shadow: inset 0 0 0 0.5px rgba(0, 0, 0, 0.3);
}

.dot-yellow {
    background: #ffbd2e;
    box-shadow: inset 0 0 0 0.5px rgba(0, 0, 0, 0.3);
}

.dot-green {
    background: #27c93f;
    box-shadow: inset 0 0 0 0.5px rgba(0, 0, 0, 0.3);
}

.terminal-title {
    position: absolute;
    left: 0;
    right: 0;
    text-align: center;
    color: #c0c0c8;
    font-size: 0.78rem;
    letter-spacing: 0.02em;
    pointer-events: none;
}

.terminal-body {
    color: #e6e6ed;
}

.size-normal .terminal-body {
    padding: 16px 18px 20px;
    font-size: 0.95rem;
    line-height: 1.55;
}

.size-compact .terminal-body {
    padding: 12px 16px 14px;
    font-size: 0.78rem;
    line-height: 1.4;
}

.size-tight .terminal-body {
    padding: 10px 14px 12px;
    font-size: 0.68rem;
    line-height: 1.35;
}

.terminal-body :deep(pre) {
    background: transparent !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    font-family: inherit !important;
    font-size: inherit !important;
}

.terminal-body :deep(code) {
    background: transparent !important;
    padding: 0 !important;
}
</style>
