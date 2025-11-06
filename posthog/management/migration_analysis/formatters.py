"""Formatters for displaying migration risk analysis results."""

import textwrap
from abc import ABC, abstractmethod

from posthog.management.migration_analysis.models import MigrationRisk, RiskLevel


class RiskFormatter(ABC):
    """Base class for risk report formatters."""

    @abstractmethod
    def format_report(self, results: list[MigrationRisk]) -> str:
        """Format a complete risk report."""
        pass

    @abstractmethod
    def format_migration(self, risk: MigrationRisk) -> str:
        """Format a single migration's risk details."""
        pass


class ConsoleTreeFormatter(RiskFormatter):
    """Formats risk reports with visual tree structure for console output."""

    # ANSI color codes
    COLOR_RESET = "\033[0m"
    COLOR_RED = "\033[91m"

    # Risk level formatting
    LEVEL_STYLES = {
        RiskLevel.SAFE: ("\033[92m", "✅"),
        RiskLevel.NEEDS_REVIEW: ("\033[93m", "⚠️"),
        RiskLevel.BLOCKED: ("\033[91m", "❌"),
    }

    def format_report(self, results: list[MigrationRisk]) -> str:
        """Format complete report with tree structure."""
        safe = [r for r in results if r.level == RiskLevel.SAFE]
        review = [r for r in results if r.level == RiskLevel.NEEDS_REVIEW]
        blocked = [r for r in results if r.level == RiskLevel.BLOCKED]

        lines = []
        lines.append(f"**Summary:** {len(safe)} Safe | {len(review)} Needs Review | {len(blocked)} Blocked")
        lines.append("")

        if blocked:
            lines.append(self._format_section(RiskLevel.BLOCKED, blocked))

        if review:
            lines.append(self._format_section(RiskLevel.NEEDS_REVIEW, review))

        if safe:
            lines.append(self._format_section(RiskLevel.SAFE, safe))

        # Add guidance section if there are risky operations
        guidance = self._collect_guidance(results)
        if guidance:
            lines.append(self._format_guidance(guidance))

        lines.append("")
        return "\n".join(lines)

    def _format_section(self, level: RiskLevel, risks: list[MigrationRisk]) -> str:
        """Format a risk level section."""
        lines = []
        _, icon = self.LEVEL_STYLES[level]

        # Add explanation for each level
        explanations = {
            RiskLevel.BLOCKED: "Causes locks or breaks compatibility",
            RiskLevel.NEEDS_REVIEW: "Requires brief lock, review for high-traffic tables",
            RiskLevel.SAFE: "No contention risk, backwards compatible",
        }
        explanation = explanations.get(level, "")
        lines.append(f"## {icon} {level.category}\n")
        lines.append(f"_{explanation}_\n")

        for risk in risks:
            lines.append(self.format_migration(risk))

        return "\n".join(lines)

    def format_migration(self, risk: MigrationRisk) -> str:
        """Format single migration with tree structure."""
        lines = ["```"]
        lines.append(risk.path)

        # Format operations with tree structure
        for idx, op_risk in enumerate(risk.operations):
            lines.extend(self._format_operation(idx, op_risk, risk))

        # Format info messages
        if risk.info_messages:
            lines.extend(self._format_info_messages(risk.info_messages))

        # Format policy violations
        if risk.policy_violations:
            lines.extend(self._format_policy_violations(risk.policy_violations))

        # Format combination warnings
        if risk.combination_risks:
            lines.extend(self._format_combination_risks(risk.combination_risks))

        lines.append("```")
        lines.append("")
        return "\n".join(lines)

    def _format_operation(self, idx: int, op_risk, risk: MigrationRisk) -> list[str]:
        """Format single operation with tree structure."""
        lines = []

        # Determine prefix based on whether there are warnings after operations
        has_warnings = risk.combination_risks or risk.policy_violations

        # Nested operations get extra indentation
        if op_risk.parent_index is not None:
            base_prefix = "  │  " if has_warnings else "  "
            prefix = base_prefix + "   "
        else:
            prefix = "  │  " if has_warnings else "  "

        # Format operation line with numbering
        op_number = f"#{idx + 1}"

        # Format details (exclude SQL to keep output clean)
        details_str = ", ".join(f"{k}: {v}" for k, v in op_risk.details.items() if k != "sql")

        # Map risk level to icon
        level_icons = {
            RiskLevel.SAFE: "✅",
            RiskLevel.NEEDS_REVIEW: "⚠️",
            RiskLevel.BLOCKED: "❌",
        }
        icon = level_icons.get(op_risk.level, "")

        if details_str:
            lines.append(f"{prefix}└─ {op_number} {icon} {op_risk.type}")
            lines.append(f"{prefix}   {op_risk.reason}")
            lines.append(f"{prefix}   {details_str}")
        else:
            lines.append(f"{prefix}└─ {op_number} {icon} {op_risk.type}: {op_risk.reason}")

        return lines

    def _format_info_messages(self, messages: list[str]) -> list[str]:
        """Format informational messages."""
        lines = []
        lines.append("  │")
        lines.append("  └──> ℹ️  INFO:")

        for message in messages:
            wrapped = textwrap.fill(message, width=72, initial_indent="       ", subsequent_indent="       ")
            lines.append(wrapped)

        return lines

    def _format_policy_violations(self, violations: list[str]) -> list[str]:
        """Format PostHog policy violations."""
        lines = []
        lines.append("  │")
        lines.append(f"  └──> {self.COLOR_RED}📋 POSTHOG POLICY VIOLATIONS:{self.COLOR_RESET}")

        for violation in violations:
            wrapped = textwrap.fill(violation, width=72, initial_indent="       ", subsequent_indent="       ")
            lines.append(wrapped)

        return lines

    def _format_combination_risks(self, warnings: list[str]) -> list[str]:
        """Format combination risk warnings."""
        lines = []
        lines.append("  │")
        lines.append(f"  └──> {self.COLOR_RED}⚠️  COMBINATION RISKS:{self.COLOR_RESET}")

        for warning in warnings:
            wrapped = textwrap.fill(warning, width=72, initial_indent="       ", subsequent_indent="       ")
            lines.append(wrapped)

        return lines

    def _collect_guidance(self, results: list[MigrationRisk]) -> dict[str, str]:
        """Collect unique guidance from all operations."""
        guidance_map = {}
        for risk in results:
            for op_risk in risk.operations:
                if op_risk.guidance and op_risk.type not in guidance_map:
                    guidance_map[op_risk.type] = op_risk.guidance
        return guidance_map

    def _format_guidance(self, guidance_map: dict[str, str]) -> str:
        """Format guidance section."""
        lines = []
        lines.append("\n## 📚 How to Deploy These Changes Safely\n")

        for op_type, guidance in sorted(guidance_map.items()):
            lines.append(f"**{op_type}:**")
            lines.append("")
            lines.append(guidance)
            lines.append("")

        return "\n".join(lines)
