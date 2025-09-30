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
        lines.append("\n" + "=" * 80)
        lines.append("Migration Risk Report")
        lines.append("=" * 80)
        lines.append(f"\nSummary: {len(safe)} Safe | {len(review)} Needs Review | {len(blocked)} Blocked\n")

        if blocked:
            lines.append(self._format_section(RiskLevel.BLOCKED, blocked))

        if review:
            lines.append(self._format_section(RiskLevel.NEEDS_REVIEW, review))

        if safe:
            lines.append(self._format_section(RiskLevel.SAFE, safe))

        lines.append("")
        return "\n".join(lines)

    def _format_section(self, level: RiskLevel, risks: list[MigrationRisk]) -> str:
        """Format a risk level section."""
        lines = []
        color, icon = self.LEVEL_STYLES[level]
        lines.append(f"\n{color}{icon} {level.category.upper()}{self.COLOR_RESET}\n")

        for risk in risks:
            lines.append(self.format_migration(risk))

        return "\n".join(lines)

    def format_migration(self, risk: MigrationRisk) -> str:
        """Format single migration with tree structure."""
        lines = [risk.path]

        # Format operations with tree structure
        for idx, op_risk in enumerate(risk.operations):
            lines.extend(self._format_operation(idx, op_risk, risk))

        # Format policy violations
        if risk.policy_violations:
            lines.extend(self._format_policy_violations(risk.policy_violations))

        # Format combination warnings
        if risk.combination_risks:
            lines.extend(self._format_combination_risks(risk.combination_risks))

        lines.append("")
        return "\n".join(lines)

    def _format_operation(self, idx: int, op_risk, risk: MigrationRisk) -> list[str]:
        """Format single operation with tree structure."""
        lines = []

        # Determine prefix based on whether there are warnings after operations
        has_warnings = risk.combination_risks or risk.policy_violations
        is_last_op = idx == len(risk.operations) - 1

        # Nested operations get extra indentation
        if op_risk.parent_index is not None:
            base_prefix = "  │  " if has_warnings and not is_last_op else "  "
            prefix = base_prefix + "   "
        else:
            prefix = "  │  " if has_warnings and not is_last_op else "  "

        # Format operation line with numbering
        op_number = f"#{idx + 1}"

        # Format details (exclude SQL to keep output clean)
        details_str = ", ".join(f"{k}: {v}" for k, v in op_risk.details.items() if k != "sql")

        if details_str:
            lines.append(f"{prefix}└─ {op_number} {op_risk.type} (score: {op_risk.score})")
            lines.append(f"{prefix}   {op_risk.reason}")
            lines.append(f"{prefix}   {details_str}")
        else:
            lines.append(f"{prefix}└─ {op_number} {op_risk.type} (score: {op_risk.score}): {op_risk.reason}")

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
