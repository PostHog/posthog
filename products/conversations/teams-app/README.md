# SupportHog Teams App

This directory contains the Microsoft Teams app manifest for the SupportHog bot.

## Setup

1. Replace `{{SUPPORT_TEAMS_APP_ID}}` in `manifest.json` with your Azure AD Application (client) ID.
2. Add `color.png` (192x192) and `outline.png` (32x32) icon files. Use the PostHog hedgehog logo or the existing `/static/services/microsoft-teams.png`.
3. Package as a ZIP file: `zip supporthog-teams.zip manifest.json color.png outline.png`
4. Upload to Teams Admin Center or sideload per-team.

## RSC Permission

The manifest declares the `ChannelMessage.Read.Group` Resource-Specific Consent permission,
which allows the bot to receive all channel messages (not just @mentions) in teams where the app is installed.
