/** @type {import('tailwindcss').Config} */
module.exports = {
  presets: [require("nativewind/preset")],
  content: ["./App.{js,ts,jsx,tsx}", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        gray: {
          1: "rgb(var(--gray-1) / <alpha-value>)",
          2: "rgb(var(--gray-2) / <alpha-value>)",
          3: "rgb(var(--gray-3) / <alpha-value>)",
          4: "rgb(var(--gray-4) / <alpha-value>)",
          5: "rgb(var(--gray-5) / <alpha-value>)",
          6: "rgb(var(--gray-6) / <alpha-value>)",
          7: "rgb(var(--gray-7) / <alpha-value>)",
          8: "rgb(var(--gray-8) / <alpha-value>)",
          9: "rgb(var(--gray-9) / <alpha-value>)",
          10: "rgb(var(--gray-10) / <alpha-value>)",
          11: "rgb(var(--gray-11) / <alpha-value>)",
          12: "rgb(var(--gray-12) / <alpha-value>)",
        },
        accent: {
          1: "rgb(var(--accent-1) / <alpha-value>)",
          2: "rgb(var(--accent-2) / <alpha-value>)",
          3: "rgb(var(--accent-3) / <alpha-value>)",
          4: "rgb(var(--accent-4) / <alpha-value>)",
          5: "rgb(var(--accent-5) / <alpha-value>)",
          6: "rgb(var(--accent-6) / <alpha-value>)",
          7: "rgb(var(--accent-7) / <alpha-value>)",
          8: "rgb(var(--accent-8) / <alpha-value>)",
          9: "rgb(var(--accent-9) / <alpha-value>)",
          10: "rgb(var(--accent-10) / <alpha-value>)",
          11: "rgb(var(--accent-11) / <alpha-value>)",
          12: "rgb(var(--accent-12) / <alpha-value>)",
          contrast: "rgb(var(--accent-contrast) / <alpha-value>)",
        },
        status: {
          success: "rgb(var(--status-success) / <alpha-value>)",
          error: "rgb(var(--status-error) / <alpha-value>)",
          warning: "rgb(var(--status-warning) / <alpha-value>)",
          info: "rgb(var(--status-info) / <alpha-value>)",
        },
        background: "rgb(var(--background) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["Open Runde"],
        mono: ["Open Runde"],
      },
    },
  },
  plugins: [],
};
