package com.example.backend.services;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.io.File;
import java.util.List;

@Service
public class ReportService {
    private final EventsService eventsService;
    private final EmailService emailService;

    @Autowired
    public ReportService(EventsService eventsService, EmailService emailService) {
        this.eventsService = eventsService;
        this.emailService = emailService;
    }

    @Async  // run in background thread (enable with @EnableAsync)
    public void emailEventsAndHeatmaps() {
        try {
            File events = eventsService.exportEventsCsv();
            File heatmaps = eventsService.exportHeatmapsCsv();
            emailService.sendReport(
                    "Events + Heatmaps Export",
                    "Attached are the latest exports.",
                    List.of(events, heatmaps)
            );
        } catch (Exception e) {
            // log properly in real code
            e.printStackTrace();
        }
    }
}