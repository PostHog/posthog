"""
Management command to analyze actual flags cache sizes for accurate memory estimation.
"""

import gzip
import json
import statistics

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.flags_cache import (
    FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
    _get_feature_flags_for_service,
    _get_feature_flags_for_teams_batch,
)
from posthog.models.team import Team


class Command(BaseHyperCacheCommand):
    help = "Analyze actual flags cache sizes to estimate memory usage"

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return FLAGS_HYPERCACHE_MANAGEMENT_CONFIG

    def add_arguments(self, parser):
        self.add_analyze_arguments(parser)

    def handle(self, *args, **options):
        sample_size = options["sample_size"]
        detailed = options["detailed"]

        # Validate input arguments to prevent resource exhaustion
        if not self.validate_sample_size(sample_size):
            return

        # Check if dedicated flags cache is configured
        if not self.check_dedicated_cache_configured():
            return

        self.stdout.write("Analyzing flags cache sizes...")

        # Get a representative sample of teams
        total_teams = Team.objects.count()
        if total_teams == 0:
            self.stdout.write(self.style.ERROR("No teams found in database"))
            return

        # Random sample of teams for unbiased statistics
        teams = list(Team.objects.select_related("organization", "project").order_by("?")[:sample_size])

        self.stdout.write(f"\nAnalyzing {len(teams)} teams (out of {total_teams} total)...")

        sizes = []
        flag_counts = []
        field_sizes: dict[str, list[float]] = {}

        # Batch-load flags for all teams at once to avoid N+1 queries
        try:
            batch_data = _get_feature_flags_for_teams_batch(teams)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Batch load failed, falling back to individual loads: {e}"))
            batch_data = None

        for team in teams:
            # Use pre-loaded data if available, otherwise load individually
            if batch_data and team.id in batch_data:
                flags_data = batch_data[team.id]
            else:
                flags_data = _get_feature_flags_for_service(team)

            if isinstance(flags_data, dict) and "flags" in flags_data:
                flags = flags_data["flags"]
                flag_counts.append(len(flags))

                # Convert to JSON
                json_str = json.dumps(flags_data, separators=(",", ":"))
                json_bytes = json_str.encode("utf-8")

                # Compress as would be stored
                compressed = gzip.compress(json_bytes, compresslevel=6)

                sizes.append(
                    {
                        "team_id": team.id,
                        "flag_count": len(flags),
                        "raw_json": len(json_bytes),
                        "compressed": len(compressed),
                        "compression_ratio": len(json_bytes) / len(compressed) if compressed else 0,
                    }
                )

                # Track field sizes across all flags
                if detailed:
                    for flag in flags:
                        for field, value in flag.items():
                            if value is not None:
                                if field not in field_sizes:
                                    field_sizes[field] = []
                                field_size = len(json.dumps(value, separators=(",", ":")))
                                field_sizes[field].append(field_size)

        if not sizes:
            self.stdout.write(self.style.ERROR("No valid flags data found"))
            return

        # Calculate statistics
        raw_sizes = [s["raw_json"] for s in sizes]
        compressed_sizes = [s["compressed"] for s in sizes]
        compression_ratios = [s["compression_ratio"] for s in sizes]

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("FLAGS CACHE SIZE ANALYSIS RESULTS"))
        self.stdout.write("=" * 60)

        self.stdout.write(f"\nSample size: {len(sizes)} teams")
        self.stdout.write(f"Total teams in database: {total_teams}")

        self.stdout.write("\n" + "-" * 40)
        self.stdout.write("Flag counts per team:")
        self.stdout.write(f"  Mean:   {statistics.mean(flag_counts):.1f}")
        self.stdout.write(f"  Median: {statistics.median(flag_counts):.0f}")
        self.stdout.write(f"  Min:    {min(flag_counts)}")
        self.stdout.write(f"  Max:    {max(flag_counts)}")
        self.stdout.write(f"  P95:    {self.calculate_percentile(flag_counts, 95):.0f}")
        self.stdout.write(f"  P99:    {self.calculate_percentile(flag_counts, 99):.0f}")

        self.stdout.write("\n" + "-" * 40)
        self.stdout.write("Uncompressed JSON sizes:")
        self.stdout.write(f"  Mean:   {self.format_bytes(statistics.mean(raw_sizes))}")
        self.stdout.write(f"  Median: {self.format_bytes(statistics.median(raw_sizes))}")
        self.stdout.write(f"  Min:    {self.format_bytes(min(raw_sizes))}")
        self.stdout.write(f"  Max:    {self.format_bytes(max(raw_sizes))}")
        self.stdout.write(f"  P95:    {self.format_bytes(self.calculate_percentile(raw_sizes, 95))}")
        self.stdout.write(f"  P99:    {self.format_bytes(self.calculate_percentile(raw_sizes, 99))}")

        self.stdout.write("\n" + "-" * 40)
        self.stdout.write("Compressed (gzip) sizes:")
        self.stdout.write(self.style.SUCCESS(f"  Mean:   {self.format_bytes(statistics.mean(compressed_sizes))}"))
        self.stdout.write(self.style.SUCCESS(f"  Median: {self.format_bytes(statistics.median(compressed_sizes))}"))
        self.stdout.write(f"  Min:    {self.format_bytes(min(compressed_sizes))}")
        self.stdout.write(f"  Max:    {self.format_bytes(max(compressed_sizes))}")
        self.stdout.write(f"  P95:    {self.format_bytes(self.calculate_percentile(compressed_sizes, 95))}")
        self.stdout.write(f"  P99:    {self.format_bytes(self.calculate_percentile(compressed_sizes, 99))}")

        self.stdout.write("\n" + "-" * 40)
        self.stdout.write("Compression ratios:")
        self.stdout.write(f"  Mean:   {statistics.mean(compression_ratios):.2f}:1")
        self.stdout.write(f"  Median: {statistics.median(compression_ratios):.2f}:1")

        # Memory projections
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("MEMORY PROJECTIONS")
        self.stdout.write("=" * 60)

        avg_compressed = statistics.mean(compressed_sizes)
        p95_compressed = self.calculate_percentile(compressed_sizes, 95)

        for team_count in [100, 1000, 5000, 10000, 50000]:
            avg_total = (avg_compressed * team_count) / (1024 * 1024)
            p95_total = (p95_compressed * team_count) / (1024 * 1024)
            self.stdout.write(f"\n{team_count:,} teams:")
            self.stdout.write(f"  Average case: {avg_total:.1f} MB")
            self.stdout.write(f"  P95 case:     {p95_total:.1f} MB")

        if detailed:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("FLAG FIELD SIZE ANALYSIS")
            self.stdout.write("=" * 60)

            # Find the largest fields by average size
            if field_sizes:
                field_avg_sizes = [(field, statistics.mean(sizes)) for field, sizes in field_sizes.items() if sizes]
                field_avg_sizes.sort(key=lambda x: x[1], reverse=True)

                self.stdout.write("\nLargest flag fields by average size:")
                for field, avg_size in field_avg_sizes[:15]:
                    count = len(field_sizes[field])
                    self.stdout.write(f"  {field:40} {self.format_bytes(avg_size)} ({count} occurrences)")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(
            self.style.WARNING(
                "\nNOTE: These are actual measurements from your database."
                "\nRedis will add ~100 bytes overhead per key."
                "\nS3 storage will be similar to compressed sizes shown above."
            )
        )

        # Update cache metrics
        self._update_cache_stats_safe()
