ALTER TABLE sharded_heatmaps MODIFY TTL toDate(timestamp) + INTERVAL 90 DAY
